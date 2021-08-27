from utils.models import *
from .qobuz_api import Qobuz


module_information = ModuleInformation(
    service_name = 'Qobuz',
    module_supported_modes = ModuleModes.download,
    flags = ModuleFlags.standard_login,
    global_settings = {'app_id': '', 'app_secret': ''},
    session_settings = {'username': '', 'password': ''},
    temporary_settings = ['token'],
    netlocation_constant = 'qobuz',
    test_url = 'https://open.qobuz.com/track/52151405'
)


class ModuleInterface:
    def __init__(self, module_controller: ModuleController):
        settings = module_controller.module_settings
        self.session = Qobuz(settings['app_id'], settings['app_secret'], module_controller.module_error)
        self.session.auth_token = module_controller.temporary_settings_controller.read('token')
        self.module_controller = module_controller

    def login(self, email, password): # Called automatically by Orpheus
        token = self.session.login(email, password)
        self.session.auth_token = token
        self.module_controller.temporary_settings_controller.set('token', token)

    def get_track_info(self, track_id: str) -> TrackInfo:
        track_data = self.session.get_track(track_id)
        album_data = track_data['album']

        # 5 = 320 kbps MP3, 6 = 16-bit FLAC, 7 = 24-bit / =< 96kHz FLAC, 27 =< 192 kHz FLAC
        quality_parse = {
            QualityEnum.LOW: 5,
            QualityEnum.MEDIUM: 5,
            QualityEnum.HIGH: 5,
            QualityEnum.LOSSLESS: 6,
            QualityEnum.HIFI: 27
        }

        file_data = self.session.get_file_url(track_id, quality_parse[self.module_controller.orpheus_options.quality_tier])

        return TrackInfo(
            track_name = track_data['title'],
            album_id = album_data['id'],
            album_name = album_data['title'],
            artist_name = track_data['performer']['name'],
            artist_id = track_data['performer']['id'],
            bit_depth = file_data['bit_depth'],
            sample_rate = file_data['sampling_rate'],
            download_type = DownloadEnum.URL,
            file_url = file_data['url'],
            cover_url = self.session.get_cover_url(album_data['image']['large']),
            tags = self.convert_tags(track_data),
            codec = CodecEnum[file_data['mime_type'].split('/')[1].replace('x-', '').replace('mpeg', 'mp3').upper()]
        )

    @staticmethod
    def convert_tags(track_data):
        album_data = track_data['album']

        return Tags(
            title = track_data['title'],
            album = album_data['title'],
            album_artist = album_data['artist']['name'],
            artist = track_data['performer']['name'],
            track_number = track_data['track_number'],
            total_tracks = album_data['tracks_count'],
            disc_number = track_data['media_number'],
            total_discs = album_data['media_count'],
            date = album_data['release_date_original'].split('-')[0],
            explicit = track_data['parental_warning'],
            isrc = track_data['isrc'] if 'isrc' in track_data else '',
            copyright = track_data['copyright'],
            genre = album_data['genre']['name'],
        )

    def get_album_info(self, album_id) -> Optional[AlbumInfo]:
        album_data = self.session.get_album(album_id)
        booklet_url = album_data['goodies'][0]['url'] if 'goodies' in album_data and len(album_data['goodies']) != 0 else None

        if self.module_controller.orpheus_options.album_search_return_only_albums and (album_data['release_type'] != 'album' or
                                                                      album_data['artist']['name'] == 'Various Artists'):
            print(f'\tIgnoring Single/EP/Various Artists: {album_data["title"]}\n')
            return None

        return AlbumInfo(
            album_name = album_data['title'],
            artist_name = album_data['artist']['name'],
            artist_id = album_data['artist']['id'],
            tracks = [str(track['id']) for track in album_data['tracks']['items']],
            booklet_url = booklet_url
        )

    def get_playlist_info(self, playlist_id) -> PlaylistInfo:
        playlist_data = self.session.get_playlist(playlist_id)

        return PlaylistInfo(
            playlist_name = playlist_data['name'],
            playlist_creator_name = playlist_data['owner']['name'],
            playlist_creator_id = playlist_data['owner']['id'],
            tracks = [str(track['id']) for track in playlist_data['tracks']['items']]
        )

    def get_artist_info(self, artist_id) -> ArtistInfo:
        artist_data = self.session.get_artist(artist_id)
        albums = [str(album['id']) for album in artist_data['albums']['items']]

        return ArtistInfo(
            artist_name = artist_data['name'],
            albums = albums
        )

    def get_track_credits(self, track_id) -> Optional[list]: # TODO: cache
        track_contributors = self.session.get_track(track_id)['performers']

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

    def search(self, query_type: DownloadTypeEnum, query: str, tags: Tags = None, limit: int = 10):
        results = {}
        if tags and tags.isrc:
            results = self.session.search(query_type.name, tags.isrc, limit)
        if not results:
            results = self.session.search(query_type.name, query, limit)

        items = []
        for i in results[query_type.name + 's']['items']:
            if query_type is DownloadTypeEnum.artist:
                artists = None
            elif query_type is DownloadTypeEnum.playlist:
                artists = [i['owner']['name']]  # TODO: replace to get all artists
            elif query_type is DownloadTypeEnum.track:
                artists = [i['performer']['name']] # TODO: replace to get all artists
            elif query_type is DownloadTypeEnum.album:
                artists = [i['artist']['name']] # TODO: replace to get all artists
            else:
                raise Exception('Query type is invalid')

            item = SearchResult(
                name = i['name'] if 'name' in i else i['title'],
                artists = artists,
                result_id = str(i['id']),
                explicit = bool(i['parental_warning']) if 'parental_warning' in i else None,
                #additional = [f'({i["maximum_sampling_rate"]}kHz/{i["maximum_bit_depth"]}bit)']
            )

            items.append(item)

        return items