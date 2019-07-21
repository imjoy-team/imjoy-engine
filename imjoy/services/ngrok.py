import sys
import os
import platform
import urllib.request
import zipfile
import stat
import subprocess
import json

def detectHostArchitecture():
        """Return the architecture as '386', 'amd64', 'arm32' or 'arm64'."""
        out = ''
        if platform.machine().lower()[:3] == 'arm':
            out += 'arm'
        if sys.maxsize > 2 ** 32:
            if out == 'arm':
                out += '64'
            else:
                out = 'amd64'
        else:
            if out == 'arm':
                out += '32'
            else:
                out = '386'
        return out

def getCdnUrl():
    env = os.environ.copy()
    arch = env.get('NGROK_ARCH', (platform.system().lower() + '-' + detectHostArchitecture()))
    cdn = env.get('NGROK_CDN_URL', 'https://bin.equinox.io')
    cdnPath = env.get('NGROK_CDN_PATH', '/c/4VmDzA7iaHb/ngrok-stable-')
    cdnFiles = {
        'darwin-386':    cdn + cdnPath + 'darwin-386.zip',
        'darwin-amd64':    cdn + cdnPath + 'darwin-amd64.zip',
        'linux-arm32':        cdn + cdnPath + 'linux-arm.zip',
        'linux-arm64':    cdn + cdnPath + 'linux-arm64.zip',
        'linux-386':    cdn + cdnPath + 'linux-386.zip',
        'linux-amd64':        cdn + cdnPath + 'linux-amd64.zip',
        'win32-386':    cdn + cdnPath + 'windows-386.zip',
        'win32-amd64':        cdn + cdnPath + 'windows-amd64.zip',
        'freebsd-386':    cdn + cdnPath + 'freebsd-386.zip',
        'freebsd-amd64':    cdn + cdnPath + 'freebsd-amd64.zip'
    }

    url = cdnFiles.get(arch)
    if url is None:
        raise Exception('ngrok - platform ' + arch + ' is not supported.')

    return url


def download_ngrok(targetdir):
    # check if data has been downloaded already
    zipPath = os.path.join(targetdir, 'ngrok.zip')
    if platform.system().lower() == 'windows':
        exePath = os.path.join(targetdir, 'ngrok.exe')
    else:
        exePath = os.path.join(targetdir, 'ngrok')
    urllib.request.urlretrieve(getCdnUrl(), zipPath)
    with zipfile.ZipFile(zipPath, 'r') as zip_ref:
        zip_ref.extractall(targetdir)
    if os.path.exists(exePath):
        st = os.stat(exePath)
        os.chmod(exePath, st.st_mode | stat.S_IEXEC)
        return exePath
    else:
        raise Exception('Failed to download or extract ngrok')

def get_public_url():
    urlData = 'http://127.0.0.1:4040/api/tunnels'
    webURL = urllib.request.urlopen(urlData)
    data = webURL.read()
    encoding = webURL.info().get_content_charset('utf-8')
    ngrok_config = json.loads(data.decode(encoding))
    return ngrok_config['tunnels'][0]['public_url']

def start_ngrok(ngrok_dir, port=9527):
    if platform.system().lower() == 'windows':
        ngrok_bin = 'ngrok.exe'
        exePath = os.path.join(ngrok_dir, ngrok_bin)
    else:
        ngrok_bin = 'ngrok'
        exePath = os.path.join(ngrok_dir, ngrok_bin)
    if not os.path.exists(exePath):

        download_ngrok(ngrok_dir)

    p = subprocess.Popen([os.path.join(ngrok_dir, ngrok_bin), 'http', str(port)], shell=False)
    
    return p

if __name__ == '__main__':
    start_ngrok('../../')
    public_url = get_public_url()
    print(public_url)