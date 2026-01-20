#!/usr/bin/env python3

import argparse
import configparser
import datetime
import json
import os
import random
import string
import sys
import time
import urllib
import urllib.parse

import flask
import requests


application = flask.Flask(__name__)
app = application  # For main.wsgi

_API_HOST = 'https://fleet-api.prd.na.vn.cloud.tesla.com'


@application.route('/')
@application.route('/<user_key>/')
@application.route('/<user_key>/<charger_id>/')
def index(user_key=None, charger_id=None):
    if not user_key:
        # Check for cookies
        user_key = flask.request.cookies.get('UserID')
        if user_key:
            return flask.redirect(flask.url_for('index', user_key=user_key))
    elif not flask.request.cookies.get('UserID'):
        response = flask.redirect(flask.url_for('index', user_key=user_key))
        response.set_cookie('UserID', user_key, expires=datetime.datetime.now() + datetime.timedelta(days=1000))
        return response

    now = datetime.datetime.now()
    ranges = [{
        'name': 'This Month',
        'start': now.replace(day=1, hour=0, minute=0, second=0),
        'end': now
    }, {
        'name': 'Last Month',
        'start': (now - datetime.timedelta(days=30)).replace(day=1, hour=0, minute=0, second=0),
        'end': now.replace(day=1, hour=0, minute=0, second=0)
    }, {
        'name': 'This Year',
        'start': now.replace(month=1, day=1, hour=0, minute=0, second=0),
        'end': now
    }, {
        'name': 'Last Year',
        'start': now.replace(year=now.year-1, month=1, day=1, hour=0, minute=0, second=0),
        'end': now.replace(month=1, day=1, hour=0, minute=0, second=0)
    }]
    range_name = flask.request.args.get('date', ranges[0]['name']).lower()
    for range in ranges:
        if range['name'].lower() == range_name:
            range_start = range['start']
            range_end = range['end']
            range_name = range['name']
            break
    else:
        range_start = ranges[0]['start']
        range_end = ranges[0]['end']
        range_name = ranges[0]['name']

    cache_path = _get_cache_path(user_key)
    if os.path.exists(cache_path) and os.stat(cache_path).st_mtime > time.time() - 60 * 60 * 24:
        charge_history = json.load(open(cache_path))
    else:
        api_key = _get_api_key(user_key)
        if api_key is None:
            return flask.redirect(flask.url_for('start_auth'))

        response = requests.get(_API_HOST + '/api/1/products', headers={
           'Content-Type': 'application/json',
           'Authorization': 'Bearer ' + api_key
        })
        sites = [x for x in response.json()['response'] if x.get('resource_type') == 'wall_connector']
        energy_site_id = sites[0]['energy_site_id']
        response = requests.get(_API_HOST + f'/api/1/energy_sites/{energy_site_id}/telemetry_history', headers={
           'Content-Type': 'application/json',
           'Authorization': 'Bearer ' + api_key
        }, params={
            'kind': 'charge',
            'start_date': '2023-01-01T00:00:00-08:00',
            'end_date': '2029-01-01T00:00:00-08:00',
            'time_zone': _get_config_setting(user_key, 'User', 'Timezone')
        })

        charge_history = response.json()['response']

        with open(cache_path, 'w') as cache:
            json.dump(charge_history, cache, indent=4)

    chargers_by_din = {}
    for charge in charge_history['charge_history']:
        if charger_id is not None and charge['din'].lower() != charger_id.lower():
            continue

        charge['start'] = datetime.datetime.fromtimestamp(charge['charge_start_time']['seconds'])
        if range_start <= charge['start'] < range_end:
            charges = chargers_by_din.setdefault(charge['din'], {
                'charges': [],
                'nickname': _get_config_setting(user_key, charge['din'], 'nickname') or charge['din'],
                'price': float(_get_config_setting(user_key, charge['din'], 'price') or
                               _get_config_setting(user_key, 'User', 'DefaultPrice'))
            })['charges']
            charges.append(charge)
            charge['cost'] = round(charge['energy_added_wh'] / 1000 * chargers_by_din[charge['din']]['price'], 2)

    for din in chargers_by_din:
        chargers_by_din[din]['total'] = sum([x['energy_added_wh'] for x in chargers_by_din[din]['charges']])
        price = float(_get_config_setting(user_key, din, 'price') or
                      _get_config_setting(user_key, 'User', 'DefaultPrice'))
        chargers_by_din[din]['cost'] = round(chargers_by_din[din]['total'] * price / 1000, 2)

    return flask.render_template('charges.html', **{
        'chargers_by_din': chargers_by_din,
        'date_range_start': range_start,
        'date_range_end': range_end,
        'date_range_name': range_name,
        'date_ranges': [x['name'] for x in ranges]
    })


@application.route('/auth/')
def start_auth():
    url = 'https://auth.tesla.com/oauth2/v3/authorize'
    args = {
        'response_type': 'code',
        'client_id': _get_client_id(),
        'redirect_uri': '%s/oauth_return/' % _get_config_setting(None, 'General', 'redirect_url'),
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
        'client_secret': _get_config_setting(None, 'Auth', 'Secret'),
        'code': flask.request.args['code'],
        'audience': _API_HOST,
        'redirect_uri': '%s/oauth_return/' % _get_config_setting(None, 'General', 'redirect_url'),
    })
    user_key = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(20))

    _set_config_setting(user_key, 'User', 'Token', token_response.json()['refresh_token'])
    return flask.redirect('/')


@application.route('/.well-known/appspecific/com.tesla.3p.public-key.pem')
def public_key():
    pubkey_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public-key.pem')
    return open(pubkey_path).read()


def _get_api_key(user_key):
    token = _get_config_setting(user_key, 'User', 'Token')
    if not token:
        return None

    token_response = requests.post('https://auth.tesla.com/oauth2/v3/token', data={
        'grant_type': 'refresh_token',
        'client_id': _get_client_id(),
        'refresh_token': token
    })
    _set_config_setting(user_key, 'User', 'Token', token_response.json()['refresh_token'])
    return token_response.json()['access_token']


def _get_client_id():
    return _get_config_setting(None, 'Auth', 'ClientID')


def _get_cache_path(user_key):
    return os.path.join(_get_user_dir(user_key), 'cache.json')


def _get_config_setting(user_key, section, key):
    parser = configparser.ConfigParser()
    parser.read(_get_config_path(user_key))
    return parser.get(section, key, fallback=None)


def _set_config_setting(user_key, section, key, value):
    parser = configparser.ConfigParser()
    parser.read(_get_config_path(user_key))
    if not parser.has_section(section):
        parser.add_section(section)
    parser.set(section, key, value)
    os.makedirs(os.path.dirname(_get_config_path(user_key)), exist_ok=True)
    with open(_get_config_path(user_key), 'w') as output:
        parser.write(output)


def _get_user_dir(user_key):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sessions', user_key)


def _get_config_path(user_key):
    if user_key is not None:
        return os.path.join(_get_user_dir(user_key), 'config.ini')
    else:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', dest='host', default='localhost')
    args = parser.parse_args()
    application.run(debug=True, host=args.host)


def register():
    if not _get_config_setting(None, 'Auth', 'PartnerToken'):
        partner_token_response = requests.post('https://auth.tesla.com/oauth2/v3/token', data={
            'grant_type': 'client_credentials',
            'client_id': _get_client_id(),
            'client_secret': _get_config_setting('Auth', 'Secret'),
            'scope': 'openid offline_access energy_device_data',
            'audience': _API_HOST,
        })
        _set_config_setting(None, 'Auth', 'PartnerToken', partner_token_response.json()['access_token'])

    response = requests.post(_API_HOST + '/api/1/partner_accounts', headers={
       'Content-Type': 'application/json',
       'Authorization': 'Bearer ' + _get_config_setting(None, 'Auth', 'PartnerToken')
    }, data=json.dumps({
        'domain': _get_config_setting(None, 'General', 'Domain')
    }))
    _set_config_setting(None, 'General', 'PartnerData', json.dumps(response.json()))


if __name__ == '__main__':
    if '--register' in sys.argv:
        register()
        sys.exit(0)

    main()
