"""Feishu CLI identity and recovery for the member's private queue."""
import json
import re
import subprocess

PROFILE = '众解深算'
# lark-cli 1.0.98 checks the declared shortcut scopes, including enrichment
# and attachment scopes, even when the command does not fetch or upload them.
SCOPES = frozenset(('search:message', 'im:message:readonly', 'im:chat:read',
                    'im:message.reactions:read', 'base:form:read', 'base:form:update',
                    'docs:document.media:upload', 'offline_access'))

MESSAGES = {
    'token_missing': '飞书本人登录凭据缺失',
    'token_expired': '飞书本人授权已失效，请重新登录',
    'access_denied': '飞书授权被拒绝，或本人无权访问申请表或通知',
    'missing_scope': '飞书本人权限不足，请重新授权并核对申请表与通知访问权限',
    'wrong_identity': '飞书登录身份与任务台绑定的成员不一致',
    'owner_unbound': '任务台尚未配置飞书成员身份，请由维护者核对并绑定',
    'verification_failed': '暂时无法核验飞书本人身份，请检查网关网络和登录状态',
}


class PlatformError(RuntimeError):
    pass


class FeishuAuthError(PlatformError):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


def command(config, args):
    return [config.get('lark_cli', 'lark-cli'), '--profile', PROFILE, *args]


def auth_error(error):
    subtype = error.get('subtype')
    if subtype in MESSAGES:
        return FeishuAuthError(subtype)
    if subtype in ('invalid_token', 'invalid_grant', 'refresh_failed', 'refresh_expired', 'expired_token'):
        return FeishuAuthError('token_expired')
    if error.get('missing_scopes') or subtype in ('permission_denied', 'insufficient_scope') or error.get('code') == 99991679:
        return FeishuAuthError('missing_scope')
    if error.get('type') == 'authentication':
        return FeishuAuthError('verification_failed')
    return None


def verify_user(config, run):
    expected = config.get('feishu_open_id')
    if not isinstance(expected, str) or not re.fullmatch(r'ou_[a-zA-Z0-9]+', expected):
        raise FeishuAuthError('owner_unbound')
    try:
        result = run(command(config, ['auth', 'status', '--json', '--verify']), timeout=15)
        data = json.loads(result.stdout if result.returncode == 0 else result.stderr)
        if result.returncode:
            raise auth_error(data.get('error', {})) or FeishuAuthError('verification_failed')
        user = data.get('identities', {}).get('user', {})
        if user.get('openId') and user['openId'] != expected:
            raise FeishuAuthError('wrong_identity')
        if user.get('tokenStatus') in ('expired', 'refresh_expired'):
            raise FeishuAuthError('token_expired')
        if user.get('status') == 'missing' or user.get('tokenStatus') == 'missing':
            raise FeishuAuthError('token_missing')
        if user.get('verified') is not True or user.get('available') is not True:
            raise FeishuAuthError('verification_failed')
        if user.get('openId') != expected:
            raise FeishuAuthError('wrong_identity')
        if not SCOPES.issubset(user.get('scope', '').split()):
            raise FeishuAuthError('missing_scope')
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError, TypeError):
        raise FeishuAuthError('verification_failed') from None
