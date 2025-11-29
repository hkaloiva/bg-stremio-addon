import copy


def merge(tmdb: dict, cinemeta: dict) -> dict:

    # Empty cases
    if not cinemeta:
        return tmdb, []
    elif not tmdb:
        return cinemeta, []
    elif not cinemeta and not tmdb:
        return {}, []
    
    # Merging
    new_videos = []
    new_meta = copy.deepcopy(cinemeta)

    if 'videos' in tmdb['meta']:
        new_meta['meta']['videos'] = tmdb['meta']['videos']

    for key in tmdb['meta']:

        if key == 'logo' and tmdb['meta'].get('logo', '') == '':
            continue
        if key == 'description' and tmdb['meta'].get('description', '') == '':
            continue

        if key not in ['imdb_id', 'videos', 'imdbRating']:
            new_meta['meta'][key] = tmdb['meta'][key]

        elif key == 'videos' and len(cinemeta['meta'].get('videos', [])) > len(tmdb['meta'].get('videos', [])):
            new_videos = merge_videos(cinemeta['meta']['videos'], tmdb['meta']['videos'])

    return new_meta, new_videos


# Videos Merger
def merge_videos(list1, list2):
    combined = list1 + list2
    merged_dict = {}

    for item in combined:
        merged_dict[item['id']] = item

    return list(merged_dict.values())