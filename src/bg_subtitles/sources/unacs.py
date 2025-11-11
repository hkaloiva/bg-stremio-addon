# -*- coding: utf-8 -*-

from .nsub import log_my, savetofile, list_key
from .common import *
import json
import io
import ssl
import gzip
from urllib import request as urllib_request, parse as urllib_parse, error as urllib_error

values = {'m':'',
          'a':'',
          't':'Submit',
          'g':'',
          'u':'',
          'action':'????',
          'y':'',
          'c':'',
          'l':'0',
          'd':''}

headers = {
            "Host": "subsunacs.net",
            "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/52.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            # Prefer gzip to avoid brotli dependency on some hosts
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
          }

url = 'https://subsunacs.net'
clean_str = r"(<div.*?>|<\/div>|<span.*?>|<\/span>|<img.*?>|<a[\s\S]*?>|<\/a>|<\/?b>|<br\s?\/>|<br>|\&\S*?;|<\/?u>|<\/?strong>|<\/?em>)"
_UNVERIFIED_CTX = ssl._create_unverified_context()


def _open_request(req: urllib_request.Request):
  """Open request with relaxed SSL verification for subsunacs.net."""
  return urllib_request.urlopen(req, context=_UNVERIFIED_CTX)

def _dedupe_entries(entries):
  seen = set()
  deduped = []
  for entry in entries:
    url_key = entry.get('url')
    if url_key and url_key in seen:
      continue
    if url_key:
      seen.add(url_key)
    deduped.append(entry)
  return deduped

def get_id_url_n(txt, list):
  soup = BeautifulSoup(txt, 'html.parser')
  # dump_src(soup, 'src.html')
  # Be tolerant: match any /subtitles/<slug-or-id>/ style, not only \w+
  for link in soup.find_all('a', href=re.compile(r'(?:/subtitles/[^\"\s]+/)$')):
    t = link.find_parent('td').find_next_siblings('td')
    y = link.find_next_sibling('span', text=True)
    if y:
      yr = y.get_text().split('(')[1].split(')')[0]
    else:
      yr = 'n/s'
    
    try:
        f_info = re.sub(clean_str, " ", str(link.get('title').encode('utf-8', 'replace').decode('utf-8')))
        s_info = f_info + '#'
        t_info = re.search('Инфо: (.+?)#', s_info)
        film_name = re.search(r'Филм:(.+?)Формат', s_info)

        if film_name:
            check_name = '#' + film_name.group(1)
            check_name = check_name.replace('# ', '')
            check_name = re.sub(clean_str, "", check_name)
        else:
            check_name = ''
        if t_info:
            fo_info = '#' + re.sub(r'[а-яА-Я,!:;\\/¤•-]|<u>|<\/?u>', '', str(t_info.group(1)))
            fo_info = fo_info.replace('  ', ' ').replace(' ', '.').replace('ETle™','')
            fo_info = fo_info.replace('..', '.').replace('..', '.').replace('..', '.').replace('..', '.').replace('..','.').replace('..', '.').replace('..', '.').replace('#.', '#').replace('#*', '').replace('*', '\n').replace('.#','').replace('#', '\n')
            if check_name != '':
                fo_info = check_name + fo_info
            else:
                pass
        else:
            fo_info = f_info
        list.append({'url': link['href'],
                  'FSrc': '[COLOR CC00FF00][B][I](subsunacs) [/I][/B][/COLOR]',
                  'info': fo_info,
                  'year': yr,
                  'cds': t[0].string.encode('utf-8', 'replace').decode('utf-8'),
                  'fps': t[1].string.encode('utf-8', 'replace').decode('utf-8'),
                  'rating': t[2].a.img and t[2].a.img.get('alt') or '0.0',
                  'id': __name__})
    except:
        list.append({'url': link['href'],
                  'FSrc': '[COLOR CC00FF00][B][I](subsunacs) [/I][/B][/COLOR]',
                  'info': re.sub(clean_str, " ", link.get('title').encode('utf-8', 'replace')),
                  'year': yr,
                  'cds': t[0].string.encode('utf-8', 'replace'),
                  'fps': t[1].string.encode('utf-8', 'replace'),
                  'rating': t[2].a.img and t[2].a.img.get('alt') or '0.0',
                  'id': __name__})
  return

def get_data(l, key):
  out = []
  for d in l:
    out.append(d[key])
  return out

def _roman_to_int_token(txt: str) -> str:
  """Convert common roman numeral episodes to arabic for broader matches.
  E.g., 'Episode IV' -> 'Episode 4'.
  """
  try:
    map_ = {
      'I': '1', 'II': '2', 'III': '3', 'IV': '4', 'V': '5',
      'VI': '6', 'VII': '7', 'VIII': '8', 'IX': '9'
    }
    def repl(m):
      return f"Episode {map_.get(m.group(1), m.group(1))}"
    return re.sub(r"\bEpisode\s+(I|II|III|IV|V|VI|VII|VIII|IX)\b", repl, txt, flags=re.IGNORECASE)
  except Exception:
    return txt


def _part_roman_to_digit(title: str) -> str:
  """Convert 'Part <Roman>' to 'Part <digit>' and also try removing the word
  'Part' to match UNACS styles that use bare numbers in slugs.

  Example: 'The Godfather Part II' -> 'The Godfather 2'
  """
  try:
    roman_map = {
      'I': '1', 'II': '2', 'III': '3', 'IV': '4', 'V': '5',
      'VI': '6', 'VII': '7', 'VIII': '8', 'IX': '9'
    }
    def repl(m):
      return roman_map.get(m.group(1).upper(), m.group(1))
    # Replace "Part <Roman>" with digit
    out = re.sub(r"\bPart\s+(I|II|III|IV|V|VI|VII|VIII|IX)\b", lambda m: repl(m), title, flags=re.IGNORECASE)
    # If we performed a replacement, also try removing the word 'Part'
    out = re.sub(r"\bPart\s+(\d+)\b", r"\1", out, flags=re.IGNORECASE)
    return out
  except Exception:
    return title


def _attempt_search(movie: str, year: str):
  """Single search attempt; returns parsed list (possibly empty)."""
  list_ = []
  values['m'] = movie
  values['y'] = year
  try:
    enc_values = urllib_parse.urlencode(values).encode("utf-8")
  except Exception:  # noqa: BLE001
    enc_values = urllib_parse.urlencode(values)
    if isinstance(enc_values, str):
      enc_values = enc_values.encode("utf-8")
  log_my('Url: ', (url), 'Headers: ', (headers), 'Values: ', (enc_values))
  try:
    request = urllib_request.Request(url + '/search.php', enc_values, headers)
    response = _open_request(request)
  except urllib_error.URLError as exc:
    log_my('subsunacs.read_sub urlopen error', exc)
    return []
  try:
    code = getattr(response, "status", None) or response.getcode()
    log_my(code, BaseHTTPServer.BaseHTTPRequestHandler.responses[code][0])
  except Exception:
    pass
  data = None
  enc = (response.info().get('Content-Encoding') or '').lower()
  try:
    raw = response.read()
    if 'gzip' in enc:
      f = gzip.GzipFile(fileobj=io.BytesIO(raw))
      data = f.read()
      f.close()
    else:
      # If no encoding provided, assume raw HTML bytes
      data = raw
  except Exception:
    return []
  get_id_url_n(data, list_)
  list_[:] = _dedupe_entries(list_)
  if run_from_xbmc == False:
    for k in list_key:
      d = get_data(list_, k)
      log_my(d)
  return list_


def read_sub(mov, year, normalized_fragment=None):
  log_my(mov, year)
  # Attempt 1: original title
  res = _attempt_search(mov, year)
  if res:
    return res
  # Attempt 2: roman numerals to numbers (Episode IV -> Episode 4)
  alt = _roman_to_int_token(mov)
  if alt != mov:
    res = _attempt_search(alt, year)
    if res:
      return res
  # Attempt 3: map 'Part <Roman>' to '2' (UNACS often indexes as bare number)
  try:
    alt_part = _part_roman_to_digit(mov)
    if alt_part != mov:
      res = _attempt_search(alt_part, year)
      if res:
        return res
  except Exception:
    pass
  # Attempt 3: simplified query for Star Wars pattern
  try:
    m = mov
    if re.search(r"\bStar\s+Wars\b", m, flags=re.IGNORECASE):
      # Try a looser query focusing on episode number or title
      simple = re.sub(r"\bEpisode\s+IV\b", "Episode 4", m, flags=re.IGNORECASE)
      simple = re.sub(r"\s*-\s*A\s+New\s+Hope\b", "", simple, flags=re.IGNORECASE)
      res = _attempt_search(simple.strip(), year)
      if res:
        return res
      res = _attempt_search("Star Wars episode 4", year)
      if res:
        return res
  except Exception:
    pass
  return res

def get_sub(id, sub_url, filename):
  s = {}
  try:
      enc_values = urllib_parse.urlencode(values).encode("utf-8")
  except Exception:  # noqa: BLE001
      enc_values = urllib_parse.urlencode(values)
      if isinstance(enc_values, str):
          enc_values = enc_values.encode("utf-8")
  headers['Referer'] = url + '/search.php?'
  try:
      request = urllib_request.Request(url + sub_url, enc_values, headers)
      response = _open_request(request)
      s['data'] = response.read()
      s['fname'] = response.info()['Content-Disposition'].split('filename=')[1].strip('"')
  except urllib_error.URLError as exc:
      log_my('subsunacs.get_sub urlopen error', exc)
      return {}
  return s
