# -*- coding: utf-8 -*-

from .nsub import log_my, savetofile, list_key
from .common import *
import xbmcgui
import requests
import re
try:
  import urllib.request
except:
  pass
import json
import io
from bs4 import BeautifulSoup

values = {'q': '','type': 'downloads_file','search_and_or': 'or','search_in': 'titles','sortby': 'relevancy'}

headers = {
    'Upgrade-Insecure-Requests' : '1',
    'User-Agent' : 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.101 Safari/537.36',
    'Content-Type' : 'application/x-www-form-urlencoded',
    'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3',
    'Accept-Encoding': 'gzip, deflate',
    'Referer' : 'http://www.easternspirit.org/forum/index.php?/files/',
    'Accept-Language' : 'en-US,en;q=0.8'
}

url = 'http://www.easternspirit.org/forum'

KodiV = xbmc.getInfoLabel('System.BuildVersion')
KodiV = int(KodiV[:2])

def get_id_url_n(txt, list):
  soup = BeautifulSoup(txt, 'html.parser')
  for link in soup.find_all("span", class_="ipsContained ipsType_break"):
    #print link
    href = link.find('a', href=True)
    title = link.getText()
    title = re.sub('[\r\n]+','',title)
    yr =  re.search('.*\((\d+)',title).group(1)
    title = re.sub(' \(.*\s+','',title)
    
    try:
        list.append({'url': href['href'].encode('utf-8', 'replace').decode('utf-8'),
                  'FSrc': '[COLOR CC00FF00][B][I](eastern) [/I][/B][/COLOR]',
                  'info': title.encode('utf-8', 'replace').decode('utf-8'),
                  'year': yr.encode('utf-8', 'replace').decode('utf-8'),
                  'cds': '',
                  'fps': '',
                  'rating': '0.0',
                  'id': __name__})
    except:
        list.append({'url': href['href'].encode('utf-8', 'replace'),
                  'FSrc': '[COLOR CC00FF00][B][I](eastern) [/I][/B][/COLOR]',
                  'info': title.encode('utf-8', 'replace'),
                  'year': yr.encode('utf-8', 'replace'),
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

  values['q'] = mov
  
  try:
      enc_values = urllib.parse.urlencode(values)
      request = urllib.request.Request(url + '/index.php?/search/&'+enc_values.replace('+','%20'), None, headers)
  except:
      enc_values = urllib.urlencode(values)
      request = urllib2.Request(url + '/index.php?/search/&'+enc_values.replace('+','%20'), None, headers)

  try:
      response = urllib.request.urlopen(request)
  except:
      response = urllib2.urlopen(request)


  if response.info().get('Content-Encoding') == 'gzip':
    try:
        try:
            buf = StringIO(response.read())
        except:
            buf = io.BytesIO(response.read())
        f = gzip.GzipFile(fileobj=buf)
        data = f.read()            
        
        log_my(response.code)
        f.close()
        buf.close()
    except:
        try:
            response = urllib.request.urlopen(request)
        except:
            response = urllib2.urlopen(request)
        data = response.read() 
  else:
    if response.info().get('X-Content-Encoding-Over-Network') == 'gzip':
      try:
          try:
              buf = StringIO(response.read())
          except:
              buf = io.BytesIO(response.read())
          f = gzip.GzipFile(fileobj=buf)
          data = f.read()            
          
          log_my(response.code)
          f.close()
          buf.close()
      except:
          try:
              response = urllib.request.urlopen(request)
          except:
              response = urllib2.urlopen(request)
          data = response.read() 
    else:
      log_my('Error: ', response.info().get('X-Content-Encoding-Over-Network'))
      return None

  get_id_url_n(data, list)
  #if run_from_xbmc == False:
  for k in list_key:
      d = get_data(list, k)
      log_my(d)

  return list


        
def getResult(subs):
    IDs = [i[1] for i in subs]
    displays = [i[0] for i in subs]
    idx = xbmcgui.Dialog().select('Select subs',displays)
    if idx < 0: return None
    return IDs[idx]
      
def get_sub(id, sub_url, filename):
    # Step 1: Open the initial page and find the "Download" button
    try:
        request = urllib.request.Request(sub_url, None, headers)
        response = urllib.request.urlopen(request)
    except:
        request = urllib2.Request(sub_url, None, headers)
        response = urllib2.urlopen(request)
    mycook = response.info().get('Set-Cookie')

    if response.info().get('Content-Encoding') == 'gzip':
        try:
            try:
                buf = StringIO(response.read())
            except:
                buf = io.BytesIO(response.read())
            f = gzip.GzipFile(fileobj=buf)
            data = f.read()
            f.close()
            buf.close()
        except:
            try:
                request = urllib.request.Request(sub_url, None, headers)
                response = urllib.request.urlopen(request)
            except:
                request = urllib2.Request(sub_url, None, headers)
                response = urllib2.urlopen(request)
            data = response.read()
    else:
        if response.info().get('X-Content-Encoding-Over-Network') == 'gzip':
            try:
                try:
                    buf = StringIO(response.read())
                except:
                    buf = io.BytesIO(response.read())
                f = gzip.GzipFile(fileobj=buf)
                data = f.read()
                f.close()
                buf.close()
            except:
                try:
                    request = urllib.request.Request(sub_url, None, headers)
                    response = urllib.request.urlopen(request)
                except:
                    request = urllib2.Request(sub_url, None, headers)
                    response = urllib2.urlopen(request)
                data = response.read()
        else:
            data = response.read()
            log_my('Error: ', response.info().get('X-Content-Encoding-Over-Network'))

    if KodiV >= 19:
        html = data.decode('utf-8')
    else:
        html = data

    # Find the first "Download" button
    soup = BeautifulSoup(html, 'html.parser')
    initial_a = soup.find('a', class_='ipsButton ipsButton_fullWidth ipsButton_large ipsButton_important')
    if not initial_a or not initial_a.get('href'):
        log_my('No initial download link found.')
        return None
    nexturl = initial_a.get('href').replace('&amp;', '&')

    # Step 2: Open the Download link and check if it's a file or a page with a list
    dheaders = {
        'Upgrade-Insecure-Requests' : '1',
        'User-Agent' : 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/60.0.3112.101 Safari/537.36',
        'Content-Type' : 'application/x-www-form-urlencoded',
        'Accept' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3',
        'Referer' : 'http://www.easternspirit.org/forum/index.php?/files/',
        'Accept-Encoding' : 'gzip, deflate',
        'Accept-Language' : 'en-US,en;q=0.8',
        'Cookie': mycook,
        'Connection': 'keep-alive',
        'Referer': nexturl,
        'Host': 'www.easternspirit.org'
    }
    ss = requests.Session()
    rfile = ss.get(nexturl, headers=dheaders)

    # Check if the response is a file download
    content_type = rfile.headers.get('Content-Type', '')
    content_disp = rfile.headers.get('Content-Disposition', '')
    is_file = False
    if 'attachment' in content_disp or ('application/' in content_type and 'html' not in content_type):
        is_file = True
    else:
        # Try to check if content is not HTML (e.g., binary)
        try:
            html2 = rfile.content.decode('utf-8')
        except Exception:
            is_file = True

    if is_file:
        file_data = rfile.content
        matchName = re.search('filename="(.+?)"', str(rfile.headers))
        name = matchName.group(1) if matchName else filename
        return {'data': file_data, 'fname': name}

    # Otherwise, parse as HTML and show selection dialog
    soup2 = BeautifulSoup(html2, 'html.parser')
    download_links = []
    for li in soup2.find_all('li', class_='ipsDataItem'):
        # Get the file name
        title_span = li.find('span', class_='ipsType_break ipsContained')
        file_name = title_span.get_text(strip=True) if title_span else 'Unknown'
        # Get the download link
        a = li.find('a', class_='ipsButton ipsButton_primary ipsButton_small')
        href = a.get('href') if a else None
        if href:
            download_links.append((file_name, href))

    if not download_links:
        log_my('No subtitle file links found on the download page.')
        return None

    # Show selection dialog
    display_names = [name for name, url in download_links]
    idx = xbmcgui.Dialog().select('Select subtitle file', display_names)
    if idx < 0:
        return None

    selected_url = download_links[idx][1]
    rfile2 = ss.get(selected_url, headers=dheaders)
    file_data = rfile2.content

    # Try to get filename from headers
    matchName = re.search('filename="(.+?)"', str(rfile2.headers))
    name = matchName.group(1) if matchName else filename

    return {'data': file_data, 'fname': name}
