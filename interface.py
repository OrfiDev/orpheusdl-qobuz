import unicodedata
from datetime import datetime

from utils.models import *
from .qobuz_api import Qobuz


module_information = ModuleInformation(
    service_name = 'Qobuz',
    module_supported_modes = ModuleModes.download | ModuleModes.credits,
    global_settings = {'app_id': '', 'app_secret': '', 'quality_format': '{sample_rate}kHz {bit_depth}bit'},
    session_settings = {'username': '', 'password': ''},
    session_storage_variables = ['token'],
    netlocation_constant = 'qobuz',
    test_url = 'https://open.qobuz.com/track/52151405'
)


class ModuleInterface:
    def __init__(self, module_controller: ModuleController):
        settings = module_controller.module_settings
        self.session = Qobuz(settings['app_id'], settings['app_secret'], module_controller.module_error) # TODO: get rid of this module_error thing
        self.session.auth_token = module_controller.temporary_settings_controller.read('token')
        self.module_controller = module_controller

        # 5 = 320 kbps MP3, 6 = 16-bit FLAC, 7 = 24-bit / =< 96kHz FLAC, 27 =< 192 kHz FLAC
        self.quality_parse = {
            QualityEnum.LOW: 5,
            QualityEnum.MEDIUM: 5,
            QualityEnum.HIGH: 5,
            QualityEnum.LOSSLESS: 6,
            QualityEnum.HIFI: 27
        }
        self.quality_tier = module_controller.orpheus_options.quality_tier
        self.quality_format = settings.get('quality_format')

    def login(self, email, password):
        token = self.session.login(email, password)
        self.session.auth_token = token
        self.module_controller.temporary_settings_controller.set('token', token)

    def get_track_info(self, track_id, quality_tier: QualityEnum, codec_options: CodecOptions, data={}):
        track_data = data[track_id] if track_id in data else self.session.get_track(track_id)
        album_data = track_data['album']

        quality_tier = self.quality_parse[quality_tier]

        main_artist = track_data.get('performer', album_data['artist'])
        artists = [
            unicodedata.normalize('NFKD', main_artist['name'])
            .encode('ascii', 'ignore')
            .decode('utf-8')
        ]

        # Filter MainArtist and FeaturedArtist from performers
        if track_data.get('performers'):
            performers = []
            for credit in track_data['performers'].split(' - '):
                contributor_role = credit.split(', ')[1:]
                contributor_name = credit.split(', ')[0]

                if 'MainArtist' in contributor_role:
                    if contributor_name not in artists:
                        artists.append(contributor_name)
                    contributor_role.remove('MainArtist')
                if 'FeaturedArtist' in contributor_role:
                    if contributor_name not in artists:
                        artists.append(contributor_name)
                    contributor_role.remove('FeaturedArtist')

                if not contributor_role:
                    continue
                performers.append(f"{contributor_name}, {', '.join(contributor_role)}")
            track_data['performers'] = ' - '.join(performers)
        artists[0] = main_artist['name']

        tags = Tags(
            album_artist = album_data['artist']['name'],
            composer = track_data['composer']['name'] if 'composer' in track_data else None,
            release_date = album_data.get('release_date_original'),
            track_number = track_data['track_number'],
            total_tracks = album_data['tracks_count'],
            disc_number = track_data['media_number'],
            total_discs = album_data['media_count'],
            isrc = track_data.get('isrc'),
            upc = album_data.get('upc'),
            copyright = track_data['copyright'],
            genres = [album_data['genre']['name']],
        )

        stream_data = self.session.get_file_url(track_id, quality_tier)
        # uncompressed PCM bitrate calculation, not quite accurate for FLACs due to the up to 60% size improvement
        bitrate = 320
        if stream_data['format_id'] in {6, 7, 27}:
            bitrate = int((stream_data['sampling_rate'] * 1000 * stream_data['bit_depth'] * 2) // 1000)

        # track and album title fix to include version tag
        track_name = track_data.get('title').rstrip()
        track_name += f' ({track_data.get("version")})' if track_data.get("version") else ''

        album_name = album_data.get('title').rstrip()
        album_name += f' ({album_data.get("version")})' if album_data.get("version") else ''

        return TrackInfo(
            name = track_name,
            album_id = album_data['id'],
            album = album_name,
            artists = artists,
            artist_id = main_artist['id'],
            bit_depth = stream_data['bit_depth'],
            bitrate = bitrate,
            sample_rate = stream_data['sampling_rate'],
            release_year = int(album_data['release_date_original'].split('-')[0]),
            explicit = track_data['parental_warning'],
            cover_url = album_data['image']['large'].split('_')[0] + '_org.jpg',
            tags = tags,
            codec = CodecEnum.FLAC if stream_data['format_id'] in {6, 7, 27} else CodecEnum.MP3,
            credits_extra_kwargs = {'data': {track_id: track_data}},
            download_extra_kwargs = {'url': stream_data['url']},
            error=f'Track "{track_data["title"]}" is not streamable!' if not track_data['streamable'] else None
        )

    def get_track_download(self, url):
        return TrackDownloadInfo(download_type=DownloadEnum.URL, file_url=url)

    def get_album_info(self, album_id):
        album_data = self.session.get_album(album_id)
        booklet_url = album_data['goodies'][0]['url'] if 'goodies' in album_data and len(album_data['goodies']) != 0 else None

        tracks, extra_kwargs = [], {}
        for track in album_data.pop('tracks')['items']:
            track_id = str(track['id'])
            tracks.append(track_id)
            track['album'] = album_data
            extra_kwargs[track_id] = track

        # get the wanted quality for an actual album quality_format string
        quality_tier = self.quality_parse[self.quality_tier]
        # TODO: Ignore sample_rate and bit_depth if album_data['hires'] is False?
        bit_depth = 24 if quality_tier == 27 and album_data['hires_streamable'] else 16
        sample_rate = album_data['maximum_sampling_rate'] if quality_tier == 27 and album_data[
            'hires_streamable'] else 44.1

        quality_tags = {
            'sample_rate': sample_rate,
            'bit_depth': bit_depth
        }

        # album title fix to include version tag
        album_name = album_data.get('title').rstrip()
        album_name += f' ({album_data.get("version")})' if album_data.get("version") else ''

        return AlbumInfo(
            name = album_name,
            artist = album_data['artist']['name'],
            artist_id = album_data['artist']['id'],
            tracks = tracks,
            release_year = int(album_data['release_date_original'].split('-')[0]),
            explicit = album_data['parental_warning'],
            quality = self.quality_format.format(**quality_tags) if self.quality_format != '' else None,
            cover_url = album_data['image']['large'].split('_')[0] + '_org.jpg',
            booklet_url = booklet_url,
            track_extra_kwargs = {'data': extra_kwargs}
        )

    def get_playlist_info(self, playlist_id):
        playlist_data = self.session.get_playlist(playlist_id)

        tracks, extra_kwargs = [], {}
        for track in playlist_data['tracks']['items']:
            track_id = str(track['id'])
            extra_kwargs[track_id] = track
            tracks.append(track_id)

        return PlaylistInfo(
            name = playlist_data['name'],
            creator = playlist_data['owner']['name'],
            creator_id = playlist_data['owner']['id'],
            release_year = datetime.utcfromtimestamp(playlist_data['created_at']).strftime('%Y'),
            tracks = tracks,
            track_extra_kwargs = {'data': extra_kwargs}
        )

    def get_artist_info(self, artist_id, get_credited_albums):
        artist_data = self.session.get_artist(artist_id)
        albums = [str(album['id']) for album in artist_data['albums']['items']]

        return ArtistInfo(
            name = artist_data['name'],
            albums = albums
        )

    def get_track_credits(self, track_id, data=None):
        track_data = data[track_id] if track_id in data else self.session.get_track(track_id)
        track_contributors = track_data.get('performers')

        # Credits look like: {name}, {type1}, {type2} - {name2}, {type2}
        credits_dict = {}
        if track_contributors:
            for credit in track_contributors.split(' - '):
                contributor_role = credit.split(', ')[1:]
                contributor_name = credit.split(', ')[0]

                for role in contributor_role:
                    # Check if the dict contains no list, create one
                    if role not in credits_dict:
                        credits_dict[role] = []
                    # Now add the name to the type list
                    credits_dict[role].append(contributor_name)

        # Convert the dictionary back to a list of CreditsInfo
        return [CreditsInfo(k, v) for k, v in credits_dict.items()]

    def search(self, query_type: DownloadTypeEnum, query, track_info: TrackInfo = None, limit: int = 10):
        results = {}
        if track_info and track_info.tags.isrc:
            results = self.session.search(query_type.name, track_info.tags.isrc, limit)
        if not results:
            results = self.session.search(query_type.name, query, limit)

        items = []
        for i in results[query_type.name + 's']['items']:
            if query_type is DownloadTypeEnum.artist:
                artists = None
                year = None
            elif query_type is DownloadTypeEnum.playlist:
                artists = [i['owner']['name']]
                year = datetime.utcfromtimestamp(i['created_at']).strftime('%Y')
            elif query_type is DownloadTypeEnum.track:
                artists = [i['performer']['name']]
                year = int(i['album']['release_date_original'].split('-')[0])
            elif query_type is DownloadTypeEnum.album:
                artists = [i['artist']['name']]
                year = int(i['release_date_original'].split('-')[0])
            else:
                raise Exception('Query type is invalid')
            name = i.get('name') or i.get('title')
            name += f" ({i.get('version')})" if i.get('version') else ''
            item = SearchResult(
                name = name,
                artists = artists,
                year = year,
                result_id = str(i['id']),
                explicit = bool(i.get('parental_warning')),
                additional = [f'{i["maximum_sampling_rate"]}kHz/{i["maximum_bit_depth"]}bit'] if "maximum_sampling_rate" in i else None,
                extra_kwargs = {'data': {str(i['id']): i}} if query_type is DownloadTypeEnum.track else {}
            )

            items.append(item)

        return items
