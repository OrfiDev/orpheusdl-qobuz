import time

from utils.utils import hash_string, create_requests_session


class Qobuz:
    def __init__(self, app_id: str, app_secret: str, exception):
        self.api_base = 'https://www.qobuz.com/api.json/0.2/'
        self.app_id = app_id
        self.app_secret = app_secret
        self.auth_token = None
        self.exception = exception
        self.s = create_requests_session()

    def headers(self):
        return {
            'X-Device-Platform': 'android',
            'X-Device-Model': 'Pixel 3',
            'X-Device-Os-Version': '10',
            'X-User-Auth-Token': self.auth_token if self.auth_token else None,
            'X-Device-Manufacturer-Id': 'ffffffff-5783-1f51-ffff-ffffef05ac4a',
            'X-App-Version': '5.16.1.5',
            'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 10; Pixel 3 Build/QP1A.190711.020))'
                          'QobuzMobileAndroid/5.16.1.5-b21041415'
        }

    def _get(self, url: str, params=None):
        if not params:
            params = {}

        r = self.s.get(f'{self.api_base}{url}', params=params, headers=self.headers())

        if r.status_code not in [200, 201, 202]:
            raise self.exception(r.text)

        return r.json()

    def login(self, email: str, password: str):
        params = {
            'username': email,
            'password': hash_string(password, 'MD5'),
            'extra': 'partner',
            'app_id': self.app_id
        }

        signature = self.create_signature('user/login', params)
        params['request_ts'] = signature[0]
        params['request_sig'] = signature[1]

        r = self._get('user/login', params)

        if 'user_auth_token' in r and r['user']['credential']['parameters']:
            self.auth_token = r['user_auth_token']
        elif not r['user']['credential']['parameters']:
            raise self.exception("Free accounts are not eligible for downloading")
        else:
            raise self.exception('Invalid username/password')

        return r['user_auth_token']

    def create_signature(self, method: str, parameters: dict):
        timestamp = str(int(time.time()))
        to_hash = method.replace('/', '')

        for key in sorted(parameters.keys()):
            if not (key == 'app_id' or key == 'user_auth_token'):
                to_hash += key + parameters[key]

        to_hash += timestamp + self.app_secret
        signature = hash_string(to_hash, 'MD5')
        return timestamp, signature

    def search(self, query_type: str, query: str, limit: int = 10):
        return self._get('catalog/search', {
            'query': query,
            'type': query_type + 's',
            'limit': limit,
            'app_id': self.app_id
        })

    def get_file_url(self, track_id: str, quality_id=27):
        params = {
            'track_id': track_id,
            'format_id': str(quality_id),
            'intent': 'stream',
            'sample': 'false',
            'app_id': self.app_id,
            'user_auth_token': self.auth_token
        }

        signature = self.create_signature('track/getFileUrl', params)
        params['request_ts'] = signature[0]
        params['request_sig'] = signature[1]

        return self._get('track/getFileUrl', params)

    def get_track(self, track_id: str):
        return self._get('track/get',  params={
            'track_id': track_id,
            'app_id': self.app_id
        })

    def get_playlist(self, playlist_id: str):
        return self._get('playlist/get',  params={
            'playlist_id': playlist_id,
            'app_id': self.app_id,
            'limit': '2000',
            'offset': '0',
            'extra': 'tracks,subscribers,focusAll'
        })

    def get_album(self, album_id: str):
        return self._get('album/get',  params={
            'album_id': album_id,
            'app_id': self.app_id,
            'extra': 'albumsFromSameArtist,focusAll'
        })

    def get_artist(self, artist_id: str):
        return self._get('artist/get', params={
            'artist_id': artist_id,
            'app_id': self.app_id,
            'extra': 'albums,playlists,tracks_appears_on,albums_with_last_release,focusAll',
            'limit': '1000',
            'offset': '0'
        })

    def get_label(self, label_id: str):
        return self._get('label/get', params={
            'label_id': label_id,
            'app_id': self.app_id,
            'extra': 'albums,focusAll', # accepted values are albums, focus, focusAll
            'limit': '1000',
            'offset': '0'
        })
