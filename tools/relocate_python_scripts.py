#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2020 ScyllaDB
#
# SPDX-License-Identifier: AGPL-3.0


import argparse
import pathlib
import os
import shutil
import io

class FilesystemFixup:
    def __init__(self, python_path, installroot):
        self.thunk = '''\
#!/usr/bin/env bash
x="$(readlink -f "$0")"
b="$(basename "$x")"
d="$(dirname "$x")"
PYTHONPATH="${{d}}:${{d}}/libexec:$PYTHONPATH" PATH="${{d}}/{pythonpath}:${{PATH}}" exec -a "$0" "${{d}}/libexec/${{b}}" "$@"
'''
        self.python_path = python_path
        self.installroot = installroot
        pathlib.Path(self.installroot).mkdir(parents=False, exist_ok=True)

    def relocated_file(self, filename):
        basename = os.path.basename(filename)
        return os.path.join("libexec", basename)

    def gen_thunk_contents(self, filename):
        base_dir = os.path.dirname(os.path.realpath(filename))
        python_path = os.path.dirname(os.path.relpath(self.python_path, base_dir))
        return self.thunk.format(pythonpath=python_path)

    def fix_shebang(self, dest, original_stat, bytes_stream):
        dest = os.path.join(self.installroot, self.relocated_file(dest))
        pathlib.Path(os.path.dirname(dest)).mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as out:
            bytes_stream.seek(0)
            os.chmod(dest, original_stat.st_mode)
            out.write(bytes_stream.read())

    def copy_as_is(self, orig, dest):
        dest = os.path.join(self.installroot, os.path.basename(dest))
        pathlib.Path(os.path.dirname(dest)).mkdir(parents=True, exist_ok=True)
        shutil.copy2(orig, dest)

    def generate_thunk(self, original_stat, out):
        bash_thunk = os.path.join(self.installroot, os.path.basename(out))
        with open(bash_thunk, "w") as f:
            os.chmod(bash_thunk, original_stat.st_mode)
            f.write(self.gen_thunk_contents(bash_thunk))

def fixup_script(output, script_name):
    '''Given a script as a parameter, fixup the script so it can be transparently called with a non-standard python3 interpreter.
    This will generate a copy of the script in the libexec/ inside the script's directory location with the shebang pointing to env
    instead of a hardcoded python location, and will replace the main script with a thunk that calls into the right interpreter
    '''

    script = os.path.realpath(script_name)
    newpath = "libexec"
    orig_stat = os.stat(script)

    if not os.access(script, os.X_OK):
        output.copy_as_is(script, script_name)
        return

    with open(script, "r") as f:
        firstline = f.readline()
        if not firstline.startswith("#!") or not "python3" in firstline:
            output.copy_as_is(script, script_name)
            return

        obj = io.BytesIO()
        shebang = "#!/usr/bin/env python3\n"

        obj.write(shebang.encode())
        for l in f:
            obj.write(l.encode())

        output.fix_shebang(script_name, orig_stat, obj)

    output.generate_thunk(orig_stat, script_name)

def fixup_scripts(output, scripts):
    for script in scripts:
        fixup_script(output, script)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description='Modify a python3 script adding indirection to its execution so it can run with a non-standard interpreter.')
    ap.add_argument('--with-python3', required=True,
                    help='path of the python3 interepreter')
    ap.add_argument('--installroot', required=True,
                    help='directory where to copy the files')
    ap.add_argument('scripts', nargs='+', help='list of python modules scripts to modify')

    args = ap.parse_args()
    archive = FilesystemFixup(args.with_python3, args.installroot)
    fixup_scripts(archive, args.scripts)
