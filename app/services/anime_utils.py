from anime import kitsu, mal

async def remove_duplicates(catalog) -> None:
    unique_items = []
    seen_ids = set()
    
    for item in catalog.get('metas') or []:
        if not isinstance(item, dict):
            continue

        item_id = item.get('id')
        if not item_id:
            continue

        # Get imdb id and animetype from catalog data
        anime_type = item.get('animeType', None)
        imdb_id = None
        if 'kitsu' in item_id:
            imdb_id, is_converted = await kitsu.convert_to_imdb(item_id, item.get('type'))
        elif 'mal_' in item_id:
            imdb_id, is_converted = await mal.convert_to_imdb(item_id.replace('_',':'), item.get('type'))
        elif 'tt' in item_id:
            imdb_id = item_id
        item['imdb_id'] = imdb_id

        # Add special, ona, ova, movies
        if imdb_id == None or anime_type != 'TV':
            unique_items.append(item)

        # Incorporate seasons
        elif imdb_id not in seen_ids:
            unique_items.append(item)
            seen_ids.add(imdb_id)

    catalog['metas'] = unique_items
