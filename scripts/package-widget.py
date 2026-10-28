"""Bundle source + a macOS-native installer, with executable ZIP permissions."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import zipfile

root=Path(__file__).resolve().parent.parent
source=root/'launchers/macos/widget'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,default=Path.home()/'results/gpuq-launcher')
args=parser.parse_args()
output=args.output_dir
output.mkdir(parents=True,exist_ok=True,mode=0o700)
release=json.loads((source/'release.json').read_text())
version=release['version']
assert re.fullmatch(r'(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})',version),'Invalid release version'
assert isinstance(release['notes'],list) and len(release['notes']) <= 20
assert all(isinstance(n,str) and len(n)<=1000 for n in release['notes'])
prefix=('var GPUQ_RELEASE_VERSION = '+json.dumps(version)+';\n').encode()
def script_bundle(*names):
 return prefix+b'\n'.join((source/name).read_bytes() for name in names)
readme='''Inspire Queue 桌面小组件 · macOS

首次安装：
1. 解压整个文件夹，双击“安装桌面小组件.command”。
2. 安装器使用 macOS 自带工具生成小面板，放在 ~/Applications/，并在桌面放一个入口，启用登录 Mac 后自动打开。
3. 面板出现后按提示选择已有 SSH config。首次需要登录时点击“完成登录”，在原登录窗口完成认证。

日常使用：
- 双击桌面“GPU 任务台小组件”，面板会检查并连接服务器。
- 可拖动位置，勾选“置顶”可让它显示在其他窗口前；未置顶时显示在桌面层。
- 显示连接状态、运行/排队/待启动数量和当前任务；每约5秒读取服务器状态。
- 模式按钮或面板获得键盘焦点时按 Shift+Tab，切换 Edit / Auto，记住选择。
- Edit 打开网页进行手动启动与排序；Auto 打开网页监看已授权队列，不自动批准新任务。
- 模式选择仅影响下次从面板打开的网页，不修改已经打开的网页。
- “打开任务台”打开完整网页。“断开连接”只关闭本面板建立的 SSH 通道。
- 若复用了原启动器连接，面板显示“已有连接”；关闭原窗口可断开它。
- 关闭小面板不会停止服务器上已经启动的 GPU 任务。

开机自启动：
- 安装新版会自动启用。已经安装小面板的 Mac，也可直接双击“开启开机自启动.command”。
- 登录本人 Mac 桌面后自动显示面板并尝试连接；需要本人 SSH 登录时仍按原提示操作。
- 自动打开不会替你点击“开始”，准备好的 GPU 任务仍等你在网页启动。
- 双击“关闭开机自启动.command”即可关闭；不会退出当前面板或停止服务器任务。
- 关闭面板后保持关闭，下次登录时再自动打开，不会反复拉起。

软件更新：
- 面板的“检查更新”打开更新窗口，可查看版本和更新说明，点击“下载并安装”。
- 启动时及每隔 6 小时检查 GitHub 更新，有新版时按钮会显示提示。只检查，不自动安装。
- 下载完整并校验通过后，先准备新版应用，再关闭旧面板、安装并重新打开。
- 更新保留 SSH 配置、窗口位置和自启动选择；服务器任务继续运行。
- 上一版应用保存在 ~/Applications/ 中，名称含 previous，供需要时手动恢复。

应用不需要额外 Python、Node 或 Xcode，不保存密码或密钥，不修改原 SSH 配置。
如需移除，先双击“关闭开机自启动.command”，再删除 ~/Applications/GPU 任务台小组件.app 及桌面入口。
自启动配置仅在本人 ~/Library/LaunchAgents/work.markflow.gpuqueue.widget.linlishuo.autostart.plist，无需管理员权限。
此包已检查 JavaScript/安装脚本语法，并测试连接状态逻辑；当前开发服务器为 Linux，AppKit 窗口及安装器尚未在 Mac 实机运行验证。
'''
files=[('安装桌面小组件.command',(source/'Install.command').read_bytes(),0o100755),
 ('开启开机自启动.command',(source/'Enable-Autostart.command').read_bytes(),0o100755),
 ('关闭开机自启动.command',(source/'Disable-Autostart.command').read_bytes(),0o100755),
 ('Autostart.command',(source/'Autostart.command').read_bytes(),0o100755),
 ('Widget.bundle.js',script_bundle('model.js','update-model.js','native.js','Widget.js'),0o100644),
 ('Updater.bundle.js',script_bundle('update-model.js','native.js','Updater.js'),0o100644),
 ('VERSION',(version+'\n').encode(),0o100644),
 ('Open-GPU-Queue.command',(root/'launchers/macos/Open-GPU-Queue.command').read_bytes(),0o100755),
 ('使用说明.txt',readme.encode(),0o100644)]
archive=output/'GPU任务台-桌面小组件-macOS.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
 for name,data,mode in files:
  item=zipfile.ZipInfo('GPU任务台桌面小组件/'+name)
  item.create_system=3;item.external_attr=mode<<16;item.compress_type=zipfile.ZIP_DEFLATED
  bundle.writestr(item,data)
payload=archive.read_bytes()
publish=output/'github-profile'
(publish/'downloads').mkdir(parents=True,exist_ok=True)
(publish/'updates').mkdir(parents=True,exist_ok=True)
filename=f'GPU-Queue-Widget-{version}-macOS.zip'
for name in (filename,'GPU-Queue-Widget-macOS.zip'):
 (publish/'downloads'/name).write_bytes(payload)
digest=hashlib.sha256(payload).hexdigest()
(publish/'downloads/SHA256SUMS').write_text(f'{digest}  {filename}\n{digest}  GPU-Queue-Widget-macOS.zip\n')
manifest={'schema':1,'version':version,'notes':release['notes'],'bytes':len(payload),'sha256':digest,
 'url':'https://raw.githubusercontent.com/Ferryyer/Ferryyer/main/downloads/'+filename}
(publish/'updates/gpu-queue-widget.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(archive)
print(publish/'updates/gpu-queue-widget.json')
