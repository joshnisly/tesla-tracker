#!/usr/bin/env python3

import argparse
import configparser
import json
import os
import sys
import urllib
import urllib.parse

import flask
import requests


application = flask.Flask(__name__)
app = application  # For main.wsgi

_API_HOST = 'https://fleet-api.prd.na.vn.cloud.tesla.com'


@application.route('/')
def index():
    api_key = _get_api_key()
    if api_key is None:
        return flask.redirect(flask.url_for('start_auth'))

    print(_get_config_setting('Auth', 'Token'))
    response = requests.get(_API_HOST + '/api/1/products', headers={
       'Content-Type': 'application/json',
       'Authorization': 'Bearer ' + api_key
    })
    print(response)
    print(response.content)
    print(response.json())
    sites = [x for x in response.json()['response'] if x.get('resource_type') == 'wall_connector']
    energy_site_id = sites[0]['energy_site_id']
    response = requests.get(_API_HOST + f'/api/1/energy_sites/{energy_site_id}/telemetry_history', headers={
       'Content-Type': 'application/json',
       'Authorization': 'Bearer ' + api_key
    }, params={
        'kind': 'charge',
        'start_date': '2023-01-01T00:00:00-08:00',
        'end_date': '2025-01-01T00:00:00-08:00',
        'time_zone': _get_config_setting('User', 'Timezone')
    })
    print(response)
    print(response.content)
    print(response.json())
    return str(response.json())


@application.route('/auth/')
def start_auth():
    url = 'https://auth.tesla.com/oauth2/v3/authorize'
    args = {
        'response_type': 'code',
        'client_id': _get_client_id(),
        'redirect_uri': 'http://localhost:5000/oauth_return/',
        'scope': 'openid offline_access energy_device_data',
        'state': 'asdfasdrfas',
    }
    redirect_url = url + '?' + urllib.parse.urlencode(args)
    return flask.render_template('auth_start.html', **{
        'redirect_url': redirect_url
    })


@application.route('/oauth_return/')
def finish_auth():
    token_response = requests.post('https://auth.tesla.com/oauth2/v3/token', data={
        'grant_type': 'authorization_code',
        'client_id': _get_client_id(),
        'client_secret': _get_config_setting('Auth', 'Secret'),
        'code': flask.request.args['code'],
        'audience': _API_HOST,
        'redirect_uri': 'http://localhost:5000/oauth_return/',
    })
    _set_config_setting('User', 'Token', token_response.json()['refresh_token'])
    return flask.redirect('/')


@application.route('/.well-known/appspecific/com.tesla.3p.public-key.pem')
def public_key():
    pubkey_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public-key.pem')
    return open(pubkey_path).read()


def _get_api_key():
    token = _get_config_setting('User', 'Token')
    if not token:
        return None

    token_response = requests.post('https://auth.tesla.com/oauth2/v3/token', data={
        'grant_type': 'refresh_token',
        'client_id': _get_client_id(),
        'refresh_token': token
    })
    _set_config_setting('User', 'Token', token_response.json()['refresh_token'])
    return token_response.json()['access_token']


def _get_client_id():
    return _get_config_setting('Auth', 'ClientID')


def _get_config_setting(section, key):
    parser = configparser.ConfigParser()
    parser.read(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini'))
    return parser.get(section, key, fallback=None)


def _set_config_setting(section, key, value):
    parser = configparser.ConfigParser()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
    parser.read(path)
    parser.set(section, key, value)
    with open(path, 'w') as output:
        parser.write(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', dest='host', default='localhost')
    args = parser.parse_args()
    application.run(debug=True, host=args.host)


def register():
    if not _get_config_setting('Auth', 'PartnerToken'):
        partner_token_response = requests.post('https://auth.tesla.com/oauth2/v3/token', data={
            'grant_type': 'client_credentials',
            'client_id': _get_client_id(),
            'client_secret': _get_config_setting('Auth', 'Secret'),
            'scope': 'openid offline_access energy_device_data',
            'audience': _API_HOST,
        })
        _set_config_setting('Auth', 'PartnerToken', partner_token_response.json()['access_token'])

    response = requests.post(_API_HOST + '/api/1/partner_accounts', headers={
       'Content-Type': 'application/json',
       'Authorization': 'Bearer ' + _get_config_setting('Auth', 'PartnerToken')
    }, data=json.dumps({
        'domain': _get_config_setting('General', 'Domain')
    }))
    _set_config_setting('General', 'PartnerData', json.dumps(response.json()))


if __name__ == '__main__':
    if '--register' in sys.argv:
        register()
        sys.exit(0)

    main()
