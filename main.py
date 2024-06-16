#!/usr/bin/env python3

import argparse
import configparser
import os
import urllib
import urllib.parse

import flask
import requests


application = flask.Flask(__name__)


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
    print(flask.request.args)

    token_response = requests.post('https://auth.tesla.com/oauth2/v3/token', data={
        'grant_type': 'authorization_code',
        'client_id': _get_client_id(),
        'client_secret': _get_config_setting('Auth', 'Secret'),
        'code': flask.request.args['code'],
        'audience': _API_HOST,
        'redirect_uri': 'http://localhost:5000/oauth_return/',
    })
    print(token_response)
    print(token_response.json())
    _set_config_setting('Auth', 'Token', token_response.json()['refresh_token'])
    return flask.redirect('/')


def _get_api_key():
    token = _get_config_setting('Auth', 'Token')
    if not token:
        return None

    token_response = requests.post('https://auth.tesla.com/oauth2/v3/token', data={
        'grant_type': 'refresh_token',
        'client_id': _get_client_id(),
        'refresh_token': token
    })
    print(token_response)
    print(token_response.json())
    _set_config_setting('Auth', 'Token', token_response.json()['refresh_token'])
    return token_response.json()['access_token']


def _get_client_id():
    return _get_config_setting('Auth', 'ClientID')


def _get_config_setting(section, key):
    parser = configparser.ConfigParser()
    parser.read(os.path.join(os.path.dirname(__file__), 'config.ini'))
    return parser.get(section, key, fallback=None)


def _set_config_setting(section, key, value):
    parser = configparser.ConfigParser()
    path = os.path.join(os.path.dirname(__file__), 'config.ini')
    parser.read(path)
    parser.set(section, key, value)
    with open(path, 'w') as output:
        parser.write(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', dest='host', default='localhost')
    args = parser.parse_args()
    application.run(debug=True, host=args.host)


if __name__ == '__main__':
    main()
