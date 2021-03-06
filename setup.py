#!/usr/bin/env python
# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from distutils.command import install
import setuptools

# Tell distutils not to put the data_files in platform-specific installation
# locations. See here for an explanation:
# https://groups.google.com/forum/#!topic/comp.lang.python/Nex7L-026uw
for scheme in install.INSTALL_SCHEMES.values():
    scheme['data'] = scheme['purelib']

setuptools.setup(
    setup_requires=['d2to1', 'pbr'],
    d2to1=True)
