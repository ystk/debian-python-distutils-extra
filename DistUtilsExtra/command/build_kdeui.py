"""distutils_extra.command.build_kdeui

Implement DistutilsExtra's 'build_kdeui' command.
"""

# Created by Martin Pitt

import subprocess
import os.path
import distutils.dir_util

class build_kdeui(distutils.cmd.Command):

    description = "compile KDE .ui files to .py with pykdeuic4"

    user_options= [('ui-files=', 'u', '.ui files that should be built'),
            ('ui-package=', 'p', 'Python package name for the generated .py files'),
            ]

    def initialize_options(self):
        self.ui_files = None
        self.ui_package = None

    def finalize_options(self):
        if not self.ui_files:
            return
        if self.ui_package is None:
            self.ui_package = '%s.kdeui' % self.distribution.get_name()

        self.destdir = os.path.join('build', 'kdeui', *self.ui_package.split('.'))
        if self.distribution.package_dir is None:
            self.distribution.package_dir = {}
        self.distribution.package_dir[self.ui_package] = self.destdir
        self.distribution.packages.append(self.ui_package)

    def run(self):
        if not self.ui_files:
            return

        distutils.dir_util.mkpath(self.destdir)
        init = os.path.join(self.destdir, '__init__.py')
        if not os.path.exists(init):
            open(init, 'w').close()

        for f in eval(self.ui_files):
            dest = os.path.join(self.destdir,
                    os.path.splitext(os.path.basename(f))[0] + '.py')
            print 'kdeui: %s -> %s' % (f, dest)
            result = subprocess.call(['python', '/usr/bin/pykdeuic4', '-o', dest, f])
            if result != 0:
                raise SystemError('The KDE .ui file %s can not be converted' % f)

