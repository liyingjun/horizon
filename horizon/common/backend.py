# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013, Yingjun Li
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import cgi
import json
import logging
import string
import random
import urllib

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import IntegrityError

from horizon.common.models import ExternalProfile
from keystoneclient.v2_0 import client as keystone_client
from openstack_auth.backend import KeystoneBackend
from weibo import APIClient


LOG = logging.getLogger(__name__)


class ExternalBackend:
    def _admin_client(self):
        return  keystone_client.Client(username=settings.ADMIN_USER,
                                      password=settings.ADMIN_PASSWORD,
                                      tenant_name=settings.ADMIN_TENANT,
                                      auth_url=settings.OPENSTACK_KEYSTONE_URL)

    def _get_sina_profile(self, token=None, request=None):
        redirect_uri = request.build_absolute_uri('authentication_callback')
        sina_client = APIClient(app_key=settings.SINA_APP_ID,
                                app_secret=settings.SINA_APP_SECRET,
                                redirect_uri=redirect_uri)

        # Get a legit access token
        access_token_dict = sina_client.request_access_token(token)
        access_token = access_token_dict.access_token
        sina_client.set_access_token(access_token,
                                     access_token_dict.expires_in)

        # Read the user's profile information
        try:
            sina_profile = sina_client.account.profile.basic.get()
            sina_id = str(sina_profile['id'])
            sina_email = sina_profile['email']
        except Exception as e:
            LOG.warn("SinaAPIClient Error: %s", e)
            messages.error(request, 'You SinaID is not authorized to login.')
            return None

        # Validate the user
        valid = False
        # Get the user's bilateral friends.
        uid = settings.SINA_GROUP_ID
        page = 1
        all_friends = []
        while True:
            try:
                friends = sina_client.friendships.friends.bilateral.get(
                                                                    uid=uid,
                                                                    page=page)
                # no more friends.
                if friends['total_number'] == 0:
                    break
            except Exception as e:
                LOG.debug('Error: %s', e)
                break
            all_friends.extend(friends['users'])
            page = page + 1
        user_ids = [user['id'] for user in all_friends]
        if sina_id in user_ids:
            valid = True
        else:
            messages.error(request,
                           "Your sinaID is not followed by %s yet." % uid)

        return dict(user_id=sina_id, user_email=sina_email,
                    access_token=access_token, valid=valid)

    def _get_tencent_profile(self, token=None, openid=None, request=None):
        if request.META.has_key('HTTP_X_FORWARDED_FOR'):
            clientip =  request.META['HTTP_X_FORWARDED_FOR']
        else:
            clientip = request.META['REMOTE_ADDR']
        redirect_uri = request.build_absolute_uri('authentication_callback')
        args = {
            'client_id': settings.TENCENT_APP_ID,
            'client_secret': settings.TENCENT_APP_SECRET,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
            'code': token,
        }

        # Get a legit access token
        target = urllib.urlopen(
                'https://open.t.qq.com/cgi-bin/oauth2/access_token?'
                + urllib.urlencode(args)).read()
        response = cgi.parse_qs(target)
        access_token = response['access_token'][-1]

        # Read the user's profile information
        try:
            args = {'format': 'json',
                    'oauth_consumer_key': settings.TENCENT_APP_ID,
                    'access_token': access_token,
                    'openid': openid,
                    'clientip': clientip,
                    'oauth_version': '2.a',
                    'scope': 'all'}
            tc_user = urllib.urlopen(
                    'http://open.t.qq.com/api/user/info?' +
                    urllib.urlencode(args)).read()
            tc_user = json.loads(tc_user)
            tencent_id = str(tc_user['data']['name'])
            tencent_email = tc_user['data'].get('email')
        except Exception as e:
            LOG.warn("Tencent Error: %s", e)
            messages.error(request, 'You QQ is not authorized to login.')
            return None

        # Validate the user.
        valid = False
        try:
            # Get the user's bilateral friends.
            uid = settings.TENCENT_GROUP_ID
            reqnum = 30
            page = 1
            all_friends = []
            # We need to get all the mutual friend, it would be slow
            # if there are too many mutual friends ):
            while True:
                args = {'format': 'json',
                    'oauth_consumer_key': settings.TENCENT_APP_ID,
                    'access_token': access_token,
                    'name': tencent_id,
                    'clientip': clientip,
                    'openid': openid,
                    'oauth_version': '2.a',
                    'scope': 'all',
                    'startindex': reqnum * (page - 1),
                    'reqnum': reqnum,
                    'install': 0}
                friends = urllib.urlopen(
                    'http://open.t.qq.com/api/friends/mutual_list?' +
                    urllib.urlencode(args)).read()
                friends = json.loads(friends)
                # no more friends
                if friends['ret'] == 5:
                    break
                all_friends.extend(friends['data']['info'])
                page = page + 1
            user_ids = [user['name'] for user in all_friends]
            if uid in user_ids:
                valid = True
            else:
                messages.error(
                    request, "Your TencentID is not followed by %s yet." % uid)
        except Exception as e:
            messages.error(request, "Failed to login tencentID %s" % e)

        return dict(user_id=tencent_id, user_email=tencent_email,
                    access_token=access_token, valid=valid)

    def authenticate(self, token=None, openid=None, request=None):
        """ Reads in a Sina/Tencent code and asks Sina/Tencent
            if it's valid and what user it points to. """
        keystone = KeystoneBackend()
        self.keystone = keystone
        # Sina weibo does not need `openid`
        if not openid:
            user_profile = self._get_sina_profile(token=token, request=request)
        else:
            user_profile = self._get_tencent_profile(token=token,
                                                     openid=openid,
                                                     request=request)
        if not user_profile:
            return
        if not user_profile['valid']:
            return

        external_id = user_profile['user_id']
        external_email = user_profile['user_email']
        access_token = user_profile['access_token']

        if not openid:
            username = "sina_%s" % external_id
            tenant_name = "sina_%s" % external_id
        else:
            username = "tencent_%s" % external_id
            tenant_name = "tencent_%s" % external_id

        password = ""
        try:
            # Try and find existing user
            external_user = ExternalProfile.objects.get(external_id=external_id)
            user = external_user.user
            # Update access_token
            external_user.access_token = access_token
            password = external_user.password
            external_user.save()
        except ExternalProfile.DoesNotExist:
            # No existing user
            try:
                try:
                    user = User.objects.create_user(username, external_email)
                except IntegrityError:
                    # Username already exists, make it unique
                    existing_user = User.objects.get(username=username)
                    existing_user.delete()
                    user = User.objects.create_user(username, external_email)
                user.save()

                password = "".join([random.choice(
                                        string.ascii_lowercase + string.digits)
                                   for i in range(8)])
                # Create the UserProfile
                external_user = ExternalProfile(user=user,
                                                external_id=external_id,
                                                access_token=access_token,
                                                password=password)
                keystone_admin = self._admin_client()

                tenant = keystone_admin.tenants.create(tenant_name,
                                                       "Auto created account",
                                                       True)
                user = keystone_admin.users.create(tenant_name,
                                                   password,
                                                   external_email,
                                                   tenant.id,
                                                   True)
                member_user_role = settings.MEMBER_USER_ROLE
                keystone_admin.roles.add_user_role(user.id,
                                                   member_user_role,
                                                   tenant.id)
                external_user.tenant_id = tenant.id
                external_user.save()
            except:
                external_user.delete()

        try:
            user = keystone.authenticate(request=request,
                                    username=username,
                                    password=password,
                                    tenant=None,
                                    auth_url=settings.OPENSTACK_KEYSTONE_URL)
            return user
        except Exception as e:
            messages.error(request, "Failed to login: %s" % e)

    def get_user(self, user_id):
        """ Just returns the user of a given ID. """
        keystone = KeystoneBackend()
        keystone.request = self.request
        return keystone.get_user(user_id)

    supports_object_permissions = False
    supports_anonymous_user = True
