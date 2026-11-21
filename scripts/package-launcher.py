"""Package an executable macOS launcher without credentials or machine keys."""
from pathlib import Path
import shutil
import zipfile

root = Path(__file__).resolve().parent.parent
output = Path.home()/'results/gpuq-launcher'
output.mkdir(parents=True, exist_ok=True, mode=0o700)
name = '打开 Inspire Queue.command'
source = root/'launchers/macos/Open-GPU-Queue.command'
launcher = output/name
shutil.copyfile(source, launcher)
launcher.chmod(0o755)
readme = '''Inspire Queue · macOS 一键打开

1. 解压，把“打开 Inspire Queue.command”拖到桌面。
2. 双击它。启动器会连接服务器并自动打开浏览器。
3. 保持连接窗口打开。下次仍然双击同一个文件，不用输入 SSH 命令。

首次使用时按窗口提示完成你原来的 SSH 登录。若 SSH 配置不在默认位置，会弹窗请你选择原来的 config 文件，并记住路径。
已经连好时，重复双击只会再次打开网页。8790 被其他应用占用时自动尝试 8791–8799。
关闭连接窗口不会停止服务器上已启动的任务。下次双击即可重新连接。

连接日志和已选配置路径保存在本机 ~/Library/Application Support/GPU Queue/。
启动器不包含密钥或密码，不修改你的 SSH 配置，也不提交或启动 GPU 任务。
'''
archive = output/'Inspire-Queue-macOS.zip'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
    for label, data, mode in [(name, source.read_bytes(), 0o100755), ('使用说明.txt', readme.encode(), 0o100644)]:
        info = zipfile.ZipInfo(label)
        info.create_system = 3
        info.external_attr = mode << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(info, data)
print(archive)
