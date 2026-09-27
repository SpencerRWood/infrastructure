#!/usr/bin/env python3
"""Resolve a single Infisical folder into a protected Compose env file."""
import argparse
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

IDENTITY = pathlib.Path('/srv/infrastructure/secrets/bootstrap/infisical-dev.json')
RUNTIME_ROOT = pathlib.Path('/srv/infrastructure/secrets/runtime')

def protected(path):
    s = path.stat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_gid != 0 or stat.S_IMODE(s.st_mode) != 0o600:
        raise ValueError('protected file permissions are invalid')

def resolve(args):
    if os.geteuid() != 0:
        raise ValueError('root required')
    os.umask(0o077)
    if not re.fullmatch(r'[a-z][a-z0-9-]*', args.environment):
        raise ValueError('invalid environment')
    if not re.fullmatch(r'/[a-z][a-z0-9/-]*', args.path) or '..' in args.path or '//' in args.path:
        raise ValueError('invalid path')
    if not args.require or len(set(args.require)) != len(args.require) or any(not re.fullmatch(r'[A-Z][A-Z0-9_]*', k) for k in args.require):
        raise ValueError('invalid required keys')
    output = pathlib.Path(args.output)
    if output.parent != RUNTIME_ROOT or output.suffix != '.env' or not re.fullmatch(r'[a-z][a-z0-9-]*\.env', output.name):
        raise ValueError('invalid output path')
    protected(IDENTITY)
    identity=json.loads(IDENTITY.read_text())
    if set(identity) != {'api_url','project_id','client_id','client_secret'} or any(not isinstance(v,str) or not v for v in identity.values()):
        raise ValueError('invalid identity configuration')
    api_url=identity['api_url'].rstrip('/')
    if not api_url.startswith('https://'):
        raise ValueError('HTTPS required')
    request=urllib.request.Request(api_url+'/api/v1/auth/universal-auth/login',
        data=urllib.parse.urlencode({'clientId':identity['client_id'],'clientSecret':identity['client_secret']}).encode(),
        headers={'Content-Type':'application/x-www-form-urlencoded','User-Agent':'Infisical-Infrastructure-Resolver/1.0'},method='POST')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request,timeout=15) as response:
        token=json.load(response)['accessToken']
    if not isinstance(token,str) or not token:
        raise ValueError('authentication failed')
    RUNTIME_ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    ds=RUNTIME_ROOT.stat()
    if ds.st_uid != 0 or ds.st_gid != 0 or stat.S_IMODE(ds.st_mode) != 0o700:
        raise ValueError('runtime directory permissions are invalid')
    fd,export_path=tempfile.mkstemp(prefix='.infisical-export-',dir=RUNTIME_ROOT)
    os.close(fd)
    try:
        env=os.environ.copy()
        env.update(INFISICAL_TOKEN=token,INFISICAL_API_URL=api_url,INFISICAL_DOMAIN=api_url,INFISICAL_DISABLE_UPDATE_CHECK='true')
        cmd=['infisical','export','--format=json','--env='+args.environment,'--path='+args.path,
             '--projectId='+identity['project_id'],'--domain='+api_url,'--expand=false',
             '--include-imports=false','--telemetry=false','--silent','--output-file='+export_path]
        result=subprocess.run(cmd,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=45,check=False)
        if result.returncode:
            raise ValueError('export failed')
        protected(pathlib.Path(export_path))
        exported=json.loads(pathlib.Path(export_path).read_text())
        if not isinstance(exported,list):
            raise ValueError('invalid export')
        values={}
        for item in exported:
            if not isinstance(item,dict) or item.get('workspace') != identity['project_id'] or item.get('secretPath') != args.path or item.get('type') != 'shared':
                raise ValueError('invalid secret metadata')
            key=item.get('key');value=item.get('value')
            if key in values or not isinstance(key,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*',key):
                raise ValueError('invalid secret key')
            if not isinstance(value,str) or not re.fullmatch(r'[\x21-\x7e]+',value):
                raise ValueError('invalid secret value')
            values[key]=value
        if not set(args.require).issubset(values):
            raise ValueError('required secret missing')
        if output.exists():protected(output)
        payload=''.join(key+'='+values[key]+'\n' for key in sorted(args.require))
        if output.exists() and output.read_text()==payload:
            print('Infisical runtime environment already current')
            return
        fd,runtime_path=tempfile.mkstemp(prefix='.infisical-runtime-',dir=RUNTIME_ROOT)
        try:
            with os.fdopen(fd,'w') as stream:
                stream.write(payload)
                stream.flush();os.fsync(stream.fileno())
            os.chmod(runtime_path,0o600)
            os.replace(runtime_path,output)
        finally:
            if os.path.exists(runtime_path):os.unlink(runtime_path)
    finally:
        if os.path.exists(export_path):os.unlink(export_path)
    print('Infisical runtime environment resolved')

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--environment',required=True)
    parser.add_argument('--path',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--require',action='append',required=True)
    try:resolve(parser.parse_args())
    except Exception:
        print('Infisical resolution failed; existing runtime file preserved',file=sys.stderr)
        sys.exit(1)
