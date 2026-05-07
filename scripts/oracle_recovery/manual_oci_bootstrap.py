from __future__ import annotations

import os
import pathlib
import sys
import webbrowser

import oci
from oci import identity
from oci_cli import cli_setup, cli_util
from oci_cli import cli_setup_bootstrap as boot

REGION = 'ap-chuncheon-1'
PROFILE = 'DEFAULT'
CONFIG = pathlib.Path.home() / '.oci' / 'config'
URL_FILE = pathlib.Path.home() / '.oci' / 'bootstrap_login_url.txt'
KEY_DIR = pathlib.Path.home() / '.oci' / 'bootstrap_default'
SESSION_DIR = pathlib.Path.home() / '.oci' / 'sessions' / PROFILE
KEY_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR.mkdir(parents=True, exist_ok=True)

orig_open_new = webbrowser.open_new

def capture_url(url: str) -> bool:
    URL_FILE.write_text(url, encoding='utf-8')
    print('OPEN_THIS_URL_BEGIN')
    print(url)
    print('OPEN_THIS_URL_END')
    try:
        return orig_open_new(url)
    except Exception:
        return False

webbrowser.open_new = capture_url

session = boot.create_user_session(region=REGION)
print('AUTH_CALLBACK_OK')

session_key_path = SESSION_DIR / 'oci_session_key.pem'
session_pub_path = SESSION_DIR / 'oci_session_key_public.pem'
session_token_path = SESSION_DIR / 'security_token'
cli_setup.write_private_key_to_file(str(session_key_path), session.private_key, None, True, True)
cli_setup.write_public_key_to_file(str(session_pub_path), session.public_key, True, True)
session_token_path.write_text(session.token, encoding='utf-8')

token_config = '\n'.join([
    '[DEFAULT]',
    f'user={session.user_ocid}',
    f'fingerprint={session.fingerprint}',
    f'key_file={session_key_path}',
    f'tenancy={session.tenancy_ocid}',
    f'region={REGION}',
    f'security_token_file={session_token_path}',
    '',
])
CONFIG.write_text(token_config, encoding='utf-8')
print('SECURITY_TOKEN_CONFIG_WRITTEN', CONFIG)

signer = oci.auth.signers.SecurityTokenSigner(session.token, session.private_key)
client = identity.IdentityClient({'region': session.region}, signer=signer)
home_region = session.region
for r in client.list_region_subscriptions(session.tenancy_ocid).data:
    if r.is_home_region:
        home_region = r.region_name
        break
client = identity.IdentityClient({'region': home_region}, signer=signer)

details = identity.models.CreateApiKeyDetails()
details.key = cli_util.serialize_key(public_key=session.public_key).decode('UTF-8')
try:
    client.upload_api_key(session.user_ocid, details)
    print('API_KEY_UPLOADED', session.fingerprint)
except oci.exceptions.ServiceError as exc:
    quota_error = (
        (exc.status == 409 and exc.code == 'ApiKeyLimitExceeded')
        or (
            exc.status == 400
            and exc.code == 'IdcsConversionError'
            and 'maximum quota limit of 3' in str(exc)
        )
    )
    if quota_error:
        print('API_KEY_LIMIT_EXCEEDED')
        keys = list(client.list_api_keys(session.user_ocid).data)
        for key in keys:
            print('EXISTING_API_KEY', key.fingerprint, key.time_created)
        if os.environ.get('OCI_BOOTSTRAP_DELETE_OLDEST_API_KEY') != '1':
            print('CONFIG_LEFT_AS_SECURITY_TOKEN')
            sys.exit(20)
        oldest = sorted(keys, key=lambda key: str(key.time_created))[0]
        client.delete_api_key(session.user_ocid, oldest.fingerprint)
        print('DELETED_OLDEST_API_KEY', oldest.fingerprint, oldest.time_created)
        client.upload_api_key(session.user_ocid, details)
        print('API_KEY_UPLOADED_AFTER_DELETE', session.fingerprint)
    else:
        raise

priv_path = KEY_DIR / 'oci_api_key.pem'
pub_path = KEY_DIR / 'oci_api_key_public.pem'
cli_setup.write_private_key_to_file(str(priv_path), session.private_key, None, True, True)
cli_setup.write_public_key_to_file(str(pub_path), session.public_key, True, True)

text = '\n'.join([
    '[DEFAULT]',
    f'user={session.user_ocid}',
    f'fingerprint={session.fingerprint}',
    f'key_file={priv_path}',
    f'tenancy={session.tenancy_ocid}',
    f'region={REGION}',
    '',
])
CONFIG.write_text(text, encoding='utf-8')
print('CONFIG_WRITTEN', CONFIG)
print('DONE')
