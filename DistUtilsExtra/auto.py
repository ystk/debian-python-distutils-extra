'''DistUtilsExtra.auto

This provides a setup() method for distutils and DistUtilsExtra which infers as
many setup() arguments as possible. The idea is that your setup.py only needs
to have the metadata and some tweaks for unusual files/paths, in a "convention
over configuration" paradigm.

This currently supports:

 * Python modules (./*.py, only in root directory)
 * Python packages (all directories with __init__.py)
 * Docbook-XML GNOME help files (help/<language>/{*.xml,*.omf,figures})
 * GtkBuilder (*.ui) [installed into prefix/share/<projectname>/]
 * Qt4 user interfaces (*.ui) [compiled with pykdeuic into Python modules]
 * D-Bus (*.conf and *.service)
 * PolicyKit (*.policy.in)
 * Desktop files (*.desktop.in) [into prefix/share/applications, or
   prefix/share/autostart if they have "autostart" anywhere in the path]
 * KDE4 notifications (*.notifyrc.in)
 * Apport hooks (apport/*) [installed into /usr/share/apport/package-hooks]
 * scripts (all in bin/, and ./<projectname>
 * Auxiliary data files (in data/*) [into prefix/share/<projectname>/]
 * automatic po/POTFILES.in (with all source files which contain _())
 * automatic MANIFEST (everything except swap and backup files, *.pyc, and
   revision control)
 * manpages (*.[0-9])
 * icons (data/icons/<size>/<category>/*.{svg,png})
 * files which should go into /etc (./etc/*, copied verbatim)
 * determining "requires" from import statements in source code
 * determining "provides" from shipped packages and modules

If you follow above conventions, then you don't need any po/POTFILES.in,
./setup.cfg, or ./MANIFEST.in, and just need the project metadata (name,
author, license, etc.) in ./setup.py.
'''

# (c) 2009 Canonical Ltd.
# Author: Martin Pitt <martin.pitt@ubuntu.com>

import os, os.path, fnmatch, stat, sys, subprocess
import compiler # TODO: deprecated
import distutils.core

from DistUtilsExtra import __version__ as __pkgversion
from DistUtilsExtra.command import *
import distutils.dir_util
import distutils.command.clean
import distutils.command.sdist
import distutils.command.install
import distutils.filelist

__version__ = __pkgversion

# FIXME: global variable, to share with build_i18n_auto
src = {}
src_all = {}

def setup(**attrs):
    '''Auto-inferring extension of standard distutils.core.setup()'''
    global src
    global src_all
    src_all = src_find(attrs)
    src = src_all.copy()

    # src_find() removes explicit scripts, but we need them for automatic
    # POTFILE.in building and requires
    src_all.update(set(attrs.get('scripts', [])))

    src_mark(src, 'setup.py')
    src_markglob(src, 'setup.cfg')

    # mark files in etc/*, handled by install_auto
    # don't install DistUtilsExtra if bundled with a source tarball
    # ignore packaging
    ignore_dirs = ['etc', 'DistUtilsExtra', 'debian']
    
    for f in src.copy():
        for d in ignore_dirs:
            if f.startswith(d + os.path.sep):
                src.remove(f)

    __cmdclass(attrs)
    __modules(attrs, src)
    __packages(attrs, src)
    __provides(attrs, src)
    __dbus(attrs, src)
    __apport_hooks(attrs, src)
    __data(attrs, src)
    __scripts(attrs, src)
    __stdfiles(attrs, src)
    __gtkbuilder(attrs, src)
    __manpages(attrs, src)

    if 'clean' not in sys.argv:
        __requires(attrs, src_all)

    distutils.core.setup(**attrs)

    if src:
        print 'WARNING: the following files are not recognized by DistUtilsExtra.auto:'
        for f in sorted(src):
            print ' ', f

#
# parts of setup()
#

class clean_build_tree(distutils.command.clean.clean):

    description = 'clean up build/ directory'

    def run(self):
        # clean build/mo
        if os.path.isdir('build'):
            distutils.dir_util.remove_tree('build')
        distutils.command.clean.clean.run(self)

def __cmdclass(attrs):
    '''Default cmdclass for DistUtilsExtra'''

    v = attrs.setdefault('cmdclass', {})
    v.setdefault('build', build_extra.build_extra)
    v.setdefault('build_help', build_help_auto)
    v.setdefault('build_i18n', build_i18n_auto)
    v.setdefault('build_icons', build_icons.build_icons)
    v.setdefault('build_kdeui', build_kdeui_auto)
    v.setdefault('install', install_auto)
    v.setdefault('clean', clean_build_tree)
    v.setdefault('sdist', sdist_auto)

def __modules(attrs, src):
    '''Default modules'''

    if 'py_modules' in attrs:
        for mod in attrs['py_modules']:
            src_markglob(src, os.path.join(mod, '*.py'))
        return

    mods = attrs.setdefault('py_modules', [])

    for f in src_fileglob(src, '*.py'):
        if os.path.sep not in f:
            mods.append(os.path.splitext(f)[0])
            src_markglob(src, f)

def __packages(attrs, src):
    '''Default packages'''

    if 'packages' in attrs:
        for pkg in attrs['packages']:
            src_markglob(src, os.path.join(pkg, '*.py'))
        return

    packages = attrs.setdefault('packages', [])

    for f in src_fileglob(src, '__init__.py'):
        if f.startswith('data' + os.path.sep):
            continue
        pkg = os.path.dirname(f)
        packages.append(pkg)
        src_markglob(src, os.path.join(pkg, '*.py'))

def __dbus(attrs, src):
    '''D-Bus configuration and services'''

    v = attrs.setdefault('data_files', [])

    # /etc/dbus-1/system.d/*.conf
    dbus_conf = []
    for f in src_fileglob(src, '*.conf'):
        if '-//freedesktop//DTD D-BUS Bus Configuration' in open(f).read():
            src_mark(src, f)
            dbus_conf.append(f)
    if dbus_conf:
        v.append(('/etc/dbus-1/system.d/', dbus_conf))

    session_service = []
    system_service = []
    # dbus services
    for f in src_fileglob(src, '*.service'):
        lines = [l.strip() for l in open(f).readlines()]
        if '[D-BUS Service]' not in lines:
            continue
        for l in lines:
            if l.startswith('User='):
                src_mark(src, f)
                system_service.append(f)
                break
        else:
            src_mark(src, f)
            session_service.append(f)
    if system_service:
        v.append(('share/dbus-1/system-services', system_service))
    if session_service:
        v.append(('share/dbus-1/services', session_service))

def __apport_hooks(attrs, src):      
    '''Apport hooks'''  
    v = attrs.setdefault('data_files', [])

    # files will be copied to /usr/share/apport/package-hooks/
    hooks = []
    assert 'name' in attrs, 'You need to set the "name" property in setup.py'
    for f in src_fileglob(src, '*.py'):
        if f.startswith('apport/'):
            hooks.append(f)
            src_mark(src, f)
    if hooks:
        v.append(('share/apport/package-hooks/', hooks))

def __data(attrs, src):
    '''Install auxiliary data files.

    This installs everything from data/ except data/icons/ and *.in files (which
    are handled differently) into prefix/share/<projectname>/.
    '''
    v = attrs.setdefault('data_files', [])

    assert 'name' in attrs, 'You need to set the "name" property in setup.py'

    data_files = []
    for f in src.copy():
        if f.startswith('data/') and not f.startswith('data/icons/') and \
                not f.endswith('.desktop.in') and not f.endswith('*.notifyrc.in'):
            if not os.path.islink(f):
                # symlinks are handled in install_auto
                v.append((os.path.join('share', attrs['name'], os.path.dirname(f[5:])), [f]))
            src_mark(src, f)

def __scripts(attrs, src):
    '''Install scripts.

    This picks executable scripts in bin/*, and an executable ./<projectname>.
    Other scripts have to be added manually; this is to avoid automatically
    installing test suites, build scripts, etc.
    '''
    assert 'name' in attrs, 'You need to set the "name" property in setup.py'

    scripts = []
    for f in src.copy():
        if f.startswith('bin/') or f == attrs['name']:
            st = os.lstat(f)
            if stat.S_ISREG(st.st_mode) and st.st_mode & stat.S_IEXEC:
                scripts.append(f)
                src_mark(src, f)
            elif stat.S_ISLNK(st.st_mode):
                # symlinks are handled in install_auto
                src_mark(src, f)

    if scripts:
        v = attrs.setdefault('scripts', [])
        v += scripts

def __stdfiles(attrs, src):
    '''Install/mark standard files.

    This covers COPYING, AUTHORS, README, etc.
    '''
    src_markglob(src, 'COPYING*')
    src_markglob(src, 'LICENSE*')
    src_markglob(src, 'AUTHORS')
    src_markglob(src, 'MANIFEST.in')
    src_markglob(src, 'MANIFEST')
    src_markglob(src, 'TODO')

    # install all README* from the root directory
    readme = []
    for f in src_fileglob(src, 'README*').union(src_fileglob(src, 'NEWS')):
        if os.path.sep not in f:
            readme.append(f)
            src_mark(src, f)
    if readme:
        assert 'name' in attrs, 'You need to set the "name" property in setup.py'

        attrs.setdefault('data_files', []).append((os.path.join('share', 'doc',
            attrs['name']), readme))

def __gtkbuilder(attrs, src):
    '''Install GtkBuilder *.ui files'''

    ui = []
    for f in src_fileglob(src, '*.ui'):
        contents = open(f).read()
        if ('<interface>\n' in contents or '<interface ' in contents) and 'class="Gtk' in contents:
            src_mark(src, f)
            ui.append(f)
    if ui:
        assert 'name' in attrs, 'You need to set the "name" property in setup.py'

        attrs.setdefault('data_files', []).append((os.path.join('share', 
            attrs['name']), ui))

def __manpages(attrs, src):
    '''Install manpages'''

    mans = {}
    for f in src_fileglob(src, '*.[0123456789]'):
        line = open(f).readline()
        if line.startswith('.TH '):
            src_mark(src, f)
            mans.setdefault(f[-1], []).append(f)
    v = attrs.setdefault('data_files', [])
    for section, files in mans.iteritems():
        v.append((os.path.join('share', 'man', 'man' + section), files))

def __external_mod(module, attrs):
    '''Check if given Python module is not included in Python or locally'''

    # filter out locally provided modules
    if module in attrs['provides']:
        return False
    for m in _module_parents(module):
        if m in attrs['provides']:
            return False

    try:
        path = __import__(module).__file__
    except ImportError:
        print >> sys.stderr, 'ERROR: Python module %s not found' % module
        return False
    except AttributeError: # builtin modules
        return False

    return 'dist-packages' in path or 'site-packages' in path or \
            not path.startswith(os.path.dirname(os.__file__))

def __add_imports(imports, file, attrs):
    '''Add all imported modules from file to imports set.

    This filters out modules which are shipped with Python itself.
    '''
    try:
        ast = compiler.parseFile(file)

        for node in ast.node.nodes:
            if isinstance(node, compiler.ast.Import):
                for name, _ in node.names:
                    if __external_mod(name, attrs):
                        imports.add(name)
            if isinstance(node, compiler.ast.From):
                if __external_mod(node.modname, attrs):
                    imports.add(node.modname)
    except SyntaxError, e:
        print >> sys.stderr, 'WARNING: syntax errors in', file, ':', e

def _module_parents(mod):
    '''Iterate over all parents of a module'''

    hierarchy = mod.split('.')
    hierarchy.pop()
    while hierarchy:
        yield '.'.join(hierarchy)
        hierarchy.pop()

def __filter_namespace(modules):
    '''Filter out modules which are already covered by a parent module
    
    E. g. this transforms ['os.path', 'os', 'foo.bar.baz', 'foo.bar'] to
    ['os', 'foo.bar'].
    '''
    result = set()

    for m in modules:
        for p in _module_parents(m):
            if p in modules:
                break
        else:
            result.add(m)

    return sorted(result)

def __requires(attrs, src_all):
    '''Determine requires (if not set explicitly)'''

    if 'requires' in attrs:
        return

    imports = set()

    # iterate over all *.py and scripts which are Python
    for s in src_all:
        if s.startswith('data' + os.path.sep):
            continue
        ext = os.path.splitext(s)[1]
        if ext == '':
            f = open(s)
            line = f.readline()
            if not line.startswith('#!') or 'python' not in line:
                continue
        elif ext != '.py':
            continue
        __add_imports(imports, s, attrs)

    attrs['requires'] = __filter_namespace(imports)

def __provides(attrs, src_all):
    '''Determine provides (if not set explicitly)'''

    if 'provides' in attrs:
        return

    provides = attrs.get('py_modules', [])
    for p in attrs.get('packages', []):
        provides.append(p.replace(os.path.sep, '.'))
    attrs['provides'] = __filter_namespace(provides)
 
#
# helper functions
#

def src_find(attrs):
    '''Find source files.
    
    This ignores all source files which are explicitly specified as setup()
    arguments.
    '''
    src = set()

    # files explicitly covered in setup() call
    explicit = set(attrs.get('scripts', []))
    for (destdir, files) in attrs.get('data_files', []):
        explicit.update(files)

    for (root, dirs, files) in os.walk('.'):
        if root.startswith('./'):
            root = root[2:]
        if root == '.':
            root = ''
        if root.startswith('.') or \
                root.split(os.path.sep, 1)[0] in ('build', 'test', 'tests'):
            continue
        # data/icons is handled by build_icons
        if root.startswith(os.path.join('data', 'icons')):
            continue
        for f in files:
            ext = os.path.splitext(f)[1]
            if f.startswith('.') or ext in ('.pyc', '~', '.mo'):
                continue
            # po/*.po is taken care of by build_i18n
            if root == 'po' and (ext == '.po' or f == 'POTFILES.in'):
                continue
            
            path = os.path.join(root, f)
            if path not in explicit:
                src.add(path)

    return src

def src_fileglob(src, fnameglob):
    '''Return set of files which match fnameglob.'''

    result = set()
    for f in src:
        if fnmatch.fnmatch(os.path.basename(f), fnameglob):
            result.add(f)
    return result

def src_mark(src, path):
    '''Remove path from src.'''

    src.remove(path)

def src_markglob(src, pathglob):
    '''Remove all paths from src which match pathglob.'''

    for f in src.copy():
        if fnmatch.fnmatch(f, pathglob):
            src.remove(f)

#
# Automatic setup.cfg
#

class build_help_auto(build_help.build_help):
    def finalize_options(self):
        build_help.build_help.finalize_options(self)
        global src
        
        for data_set in self.get_data_files():
            for filepath in data_set[1]:
                src.remove(filepath)

class build_i18n_auto(build_i18n.build_i18n):
    def finalize_options(self):
        build_i18n.build_i18n.finalize_options(self)
        global src
        global src_all

        # add PolicyKit files
        policy_files = []
        for f in src_fileglob(src, '*.policy.in'):
            src_mark(src, f)
            policy_files.append(f)
        if policy_files:
            # check if we have PolicyKit 1 API
            if subprocess.call(['grep', '-q', 'org\.freedesktop\.PolicyKit1'] +
                    list(src_fileglob(src_all, '*.py')),
                    stderr=subprocess.PIPE) == 0:
                destdir = os.path.join('share', 'polkit-1', 'actions')
            else:
                destdir = os.path.join('share', 'PolicyKit', 'policy')
            try:
                xf = eval(self.xml_files)
            except TypeError:
                xf = []
            xf.append((destdir, policy_files))
            self.xml_files = repr(xf)

        # add desktop files
        desktop_files = []
        autostart_files = []
        notify_files = []
        for f in src_fileglob(src, '*.desktop.in'):
            src_mark(src, f)
            if 'autostart' in f:
                autostart_files.append(f)
            else:
                desktop_files.append(f)
        for f in src_fileglob(src, '*.notifyrc.in'):
            src_mark(src, f)
            notify_files.append(f)
        try:
            df = eval(self.desktop_files)
        except TypeError:
            df = []
        if desktop_files:
            df.append(('share/applications', desktop_files))
        if autostart_files:
            df.append(('share/autostart', autostart_files))
        if notify_files:
            df.append(('share/kde4/apps/' + self.distribution.get_name(), notify_files))
        self.desktop_files = repr(df)
        
        # mark PO template as known to handle
        try:
            src_mark(src, os.path.join(self.po_dir, self.distribution.get_name() + '.pot'))
        except KeyError:
            pass

    def run(self):
        '''Build a default POTFILES.in'''

        auto_potfiles_in = False
        exe_symlinks = []
        global src_all
        try:
            if not os.path.exists(os.path.join('po', 'POTFILES.in')):
                files = src_fileglob(src_all, '*.py')
                files.update(src_fileglob(src_all, '*.desktop.in'))
                files.update(src_fileglob(src_all, '*.notifyrc.in'))
                files.update(src_fileglob(src_all, '*.policy.in'))

                for f in src_fileglob(src_all, '*.ui'):
                    contents = open(f).read()
                    if ('<interface>\n' in contents or '<interface ' in contents) and 'class="Gtk' in contents:
                        files.add('[type: gettext/glade]' + f)

                # find extensionless executable scripts which are Python files, and
                # generate a temporary *.py alias, so that they get caught by
                # intltool
                for f in reduce(lambda x, y: x.union(y[1]), self.distribution.data_files, src_all):
                    f_py = f + '.py'
                    if os.access(f, os.X_OK) and os.path.splitext(f)[1] == '' and \
                            not os.path.exists(f_py):
                        line = open(f).readline()
                        if line.startswith('#!') and 'python' in line:
                            os.symlink(os.path.basename(f), f_py)
                            files.add(f_py)
                            exe_symlinks.append(f_py)

                if files:
                    if not os.path.isdir('po'):
                        os.mkdir('po')
                    potfiles_in = open('po/POTFILES.in', 'w')
                    print >> potfiles_in, '[encoding: UTF-8]'
                    for f in files:
                        print >> potfiles_in, f
                    potfiles_in.close()

                    auto_potfiles_in = True

            build_i18n.build_i18n.run(self)
        finally:
            for f in exe_symlinks:
                os.unlink(f)

        if auto_potfiles_in:
            os.unlink('po/POTFILES.in')
            try:
                os.rmdir('po')
            except:
                pass

class build_kdeui_auto(build_kdeui.build_kdeui):
    def finalize_options(self):
        global src

        # add *.ui files which belong to KDE4
        kdeui_files = []
        for f in src_fileglob(src, '*.ui'):
            fd = open(f)
            # might be on the first or second line
            if fd.readline().startswith('<ui version="') or \
               fd.readline().startswith('<ui version="'):
                src_mark(src, f)
                kdeui_files.append(f)
            fd.close()
        if kdeui_files:
            try:
                uf = eval(self.ui_files)
            except TypeError:
                uf = []
            uf += kdeui_files
            self.ui_files = repr(uf)

        build_kdeui.build_kdeui.finalize_options(self)

#
# Automatic sdist
#

class sdist_auto(distutils.command.sdist.sdist):
    '''Default values for the 'sdist' command.
    
    Replace the manually maintained MANIFEST.in file by providing information
    about what the source tarball created using the 'sdist' command should
    contain in normal cases.
    
    It prevents the 'build' directory, version control related files, as well as
    compiled Python and gettext files and temporary files from being included in
    the source tarball.
    
    It's possible for subclasses to extend the 'filter_prefix' and
    'filter_suffix' properties.
    '''
    filter_prefix = ['build', '.git', '.svn', '.CVS', '.bzr', '.shelf']
    filter_suffix = ['.pyc', '.mo', '~', '.swp']
    
    def add_defaults(self):
        distutils.command.sdist.sdist.add_defaults(self)
        
        if os.path.exists('MANIFEST.in'):
            return

        self.filter_prefix.append(os.path.join('dist',
            self.distribution.get_name()))
        
        for f in distutils.filelist.findall():
            if f in self.filelist.files or \
                any(map(f.startswith, self.filter_prefix)) or \
                any(map(f.endswith, self.filter_suffix)):
                continue
            
            self.filelist.append(f)

#
# Automatic installation of ./etc/ and symlinks
#

class install_auto(distutils.command.install.install):
    def run(self):
        # install files from etc/
        if os.path.isdir('etc'):
            # work around a bug in copy_tree() which fails with "File exists" on
            # previously existing symlinks
            for f in distutils.filelist.findall('etc'):
                if not f.startswith('etc' + os.path.sep) or not os.path.islink(f):
                    continue
                try:
                    os.unlink(os.path.join(self.root, f))
                except OSError:
                    pass
            if not self.root:
                self.root = ''
            distutils.dir_util.copy_tree('etc', os.path.join(self.root, 'etc'),
                    preserve_times=0, preserve_symlinks=1, verbose=1)

        # install data/scripts symlinks
        for f in distutils.filelist.findall():
            if not os.path.islink(f):
                continue
            if f.startswith('bin/') or f.startswith('data/'):
                if f.startswith('bin'):
                    dir = self.install_scripts
                    dest = os.path.join(dir, os.path.sep.join(f.split(os.path.sep)[1:]))
                elif f.startswith('data/icons'):
                    dir = os.path.join(self.install_data, 'share', 'icons', 'hicolor')
                    dest = os.path.join(dir, os.path.sep.join(f.split(os.path.sep)[2:]))
                else:
                    dir = os.path.join(self.install_data, 'share', self.distribution.get_name())
                    dest = os.path.join(dir, os.path.sep.join(f.split(os.path.sep)[1:]))

                d = os.path.dirname(dest)
                if not os.path.isdir(d):
                    os.makedirs(d)
                if os.path.exists(dest):
                    os.unlink(dest)
                os.symlink(os.readlink(f), dest)

        distutils.command.install.install.run(self)

