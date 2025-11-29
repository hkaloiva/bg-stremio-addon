# -*- coding: utf-8 -*-

from .nsub import log_my, savetofile, list_key
from .common import *
import requests
import re
try:
  import urllib.request
except:
  pass
import json
import io

s = requests.Session()

values = {'search': ''}
headers = {'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3',
'Accept-Encoding': 'gzip, deflate',
'Accept-Language': 'en-US,en;q=0.9,bg-BG;q=0.8,bg;q=0.7,ru;q=0.6',
'Connection': 'keep-alive',
'Host': 'bukvi.bg',
'Referer': 'http://bukvi.bg/',
'Upgrade-Insecure-Requests': '1',
'User-Agent': 'Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/74.0.3729.131 Safari/537.36'}

url = 'bukvi.bg'
url_full = 'http://bukvi.bg'

#url = 'http://bukvi.bg/index.php?'
KodiV = xbmc.getInfoLabel('System.BuildVersion')
KodiV = int(KodiV[:2])

def get_id_url_n(txt, list):
  soup = BeautifulSoup(txt, 'html.parser')
  # dump_src(soup, 'src.html')
  for links in soup.find_all("td", {"style": ["text-align: left;"]}):
    link = links.find('a', href=True)
    info = link.text#.split('/')[0]
    #yr = re.search('.*\((\d+)',link.text).group(1)
    if KodiV >= 19:
        list.append({'url': link['href'].encode('utf-8', 'replace').decode('utf-8'),
                  'FSrc': '[COLOR CC00FF00][B][I](bukvi) [/I][/B][/COLOR]',
                  'info': info.encode('utf-8', 'replace').decode('utf-8'),
                  'year': '',
                  'cds': '',
                  'fps': '',
                  'rating': '0.0',
                  'id': __name__})        
    else:
        list.append({'url': link['href'].encode('utf-8', 'replace'),
                  'FSrc': '[COLOR CC00FF00][B][I](bukvi) [/I][/B][/COLOR]',
                  'info': info.encode('utf-8', 'replace'),
                  'year': '',
                  'cds': '',
                  'fps': '',
                  'rating': '0.0',
                  'id': __name__})
  return

def get_data(l, key):
  out = []
  for d in l:
    out.append(d[key])
  return out

def read_sub (mov):
  list = []

  values['search'] = mov
  #values['y'] = year

  if KodiV >= 19:
      enc_values = urllib.parse.urlencode(values)
  else:
      enc_values = urllib.urlencode(values)
  log_my('Url: ', (url) +enc_values, 'Headers: ', (headers))

  try:
        connection = HTTPConnection(url)
  except:
        connection = http.client.HTTPConnection(url)
  connection.request("POST", "/index.php?", headers=headers, body=enc_values.replace('%20','+'))
  response = connection.getresponse()

  if response.status == 200 and response.getheader('content-type').split(';')[0] == 'text/html':
    r = s.get(url_full+"/index.php?"+enc_values, headers=headers)
    log_my(response.getheaders())
    data = r.text
  else:
    connection.close()
    return None

  get_id_url_n(data, list)
  #if run_from_xbmc == False:
  for k in list_key:
      d = get_data(list, k)
      log_my(d)

  return list

def get_sub(id, sub_url, filename): 
  s = {}
  headers['Referer'] = url_full
  if KodiV >= 19:
      request = urllib.request.Request( 'http://bukvi.mmcenter.bg/load/0-0-0-' + sub_url.split("/")[-1] + '-20' , None, headers)
      response = urllib.request.urlopen(request)
  else:
      request = urllib2.Request( 'http://bukvi.mmcenter.bg/load/0-0-0-' + sub_url.split("/")[-1] + '-20' , None, headers)
      response = urllib2.urlopen(request)
  s['data'] = response.read()
  s['fname'] = response.geturl().split("/")[-1]
  return s
