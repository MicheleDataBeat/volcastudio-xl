#!/usr/bin/env python3
"""Register an already-built Desktop App in the Linux application menu."""
import argparse
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--applications',type=Path,default=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'applications')
    parser.add_argument('--executable',type=Path,default=ROOT/'dist/VolcaStudio XL Desktop App/VolcaStudio XL Desktop App',help='Packaged executable to register, including a separate versioned build')
    args=parser.parse_args()
    if not sys.platform.startswith('linux'):
        parser.error('On macOS copy the .app to Applications; on Windows use the native application directory.')
    executable=args.executable.expanduser().resolve()
    if not executable.is_file():parser.error('Build the Desktop App first.')
    path=args.applications/'volcastudio-outie.desktop'
    if path.exists() and 'X-VolcaStudio-Outie=true' not in path.read_text():
        parser.error('Refusing to replace an unrelated application launcher.')
    def quoted(value):
        return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'
    args.applications.mkdir(parents=True,exist_ok=True)
    path.write_text('[Desktop Entry]\nType=Application\nName=VolcaStudio XL Desktop App\nComment=Volca Sample kits, patterns, grooves and firmware\nExec='+quoted(executable)+'\nIcon='+str(ROOT/'packaging/outie.svg')+'\nTerminal=false\nCategories=AudioVideo;Audio;Music;\nX-VolcaStudio-Outie=true\n')
    print(path)
if __name__=='__main__':main()
