"""Mac convenience build entry. Uses Android Studio's JDK and the Gradle Wrapper."""
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parent
if sys.version_info[:2] != (3,12):
    raise SystemExit('請使用Python3.12，例如 python3.12 build_apk.py')
env=dict(os.environ)
jdk=Path('/Applications/Android Studio.app/Contents/jbr/Contents/Home')
if jdk.is_dir():env['JAVA_HOME']=str(jdk)
env['EVENT_TODO_BUILD_PYTHON']=sys.executable
sdk=Path(env.get('ANDROID_HOME',str(Path.home()/'Library/Android/sdk')))
if not sdk.is_dir():raise SystemExit('找不到Android SDK，請先用Android Studio安裝。')
properties=root/'local.properties'
if not properties.exists():properties.write_text('sdk.dir='+str(sdk)+'\n',encoding='utf-8')
subprocess.run(['/bin/sh',str(root/'gradlew'),'assembleDebug','lintDebug','--console=plain'],cwd=root,env=env,check=True)
print('APK:',root/'app/build/outputs/apk/debug/app-debug.apk')
