from ast import List
import random
import threading
from typing import Any, Generator, Optional, Set, Tuple
import requests
from bs4 import BeautifulSoup as bs
import argparse
import time
import os.path
import urllib.parse
from url_normalize import url_normalize
from collections import namedtuple
import os
import sys

if not os.path.isdir('out'):
    os.mkdir('out')

os.chdir('out')

DELAY = 0.1

pathcomponents = namedtuple('pathcomponents', ('directory', 'filename'))
urltolocalcorrespondance = namedtuple('urltolocalcorrespondance', ('pathcomponents', 'url'))

RED = '\033[31m'
GREEN = '\033[32m'
YELLOW = '\033[33m'
BLUE = '\033[34m'
MAGENTA = '\033[35m'
CYAN = '\033[35m'
YELLOW = '\033[35m'
BLACK = '\033[0m'

status_thread = None
_print = print

width = os.get_terminal_size().columns
lock = threading.RLock()

if not os.environ.get('STREAM_OUTPUT', False):

    def status_print(message):
        with lock:
            print("\n{}".format(message))
            _print("\033[F")
            sys.stdout.flush()

    def print(message):
        with lock:
            _print(" " * width, end='')
            _print("\x08" * width, end='')
            _print(message, end='')
            sys.stdout.flush()
            _print("\x08" * width, end='')
else:
    def status_print(message):
        print(message)

    _print = print

    def print(message):
        _print(message.replace('\n', '').replace('\x08', '').replace('\033[F', ''))


def urltopathcomponents(url_path: str) -> pathcomponents:
    if url_path.endswith('/'):
        url_path = url_path.rstrip('/')

    * directories, filename = url_path.split('/')
    if not directories:
        return pathcomponents('./', filename)

    if filename in ('/', '', '.html', '.htm'):
        filename = 'index.html'

    return pathcomponents(os.path.join(*directories), filename)


def downloadsite(url_root: str, first_page: str, overwrite=False):
    c = Crawler(url_root, first_page)

    def target() -> Generator[Tuple[Any, str], None, None]:
        print("starting")
        i = iter(c)
        while True:
            try:
                obj = next(i)
                if obj is None:
                    continue
                ((directory, filename), url) = obj
                print("[⤵️] Downloading url {}".format(url))
                req = requests.get(url)
                content = req.text
                destination = os.path.join(directory, filename) + '.html'
                if os.path.exists(destination):
                    if not overwrite:
                        raise ValueError("File {} already exists. Refusing to overwrite!".format(destination))
                    else:
                        print("[❗️] Overwriting existing file {} because of -o flag".format(destination))
                with open(destination, 'w') as f:
                    f.write(content)
                # yield url, content
                timeout = DELAY + random.random() * (DELAY * 25 / 100)
                print(f"[🛑] Waiting {timeout} seconds")
                time.sleep(timeout)
            except StopIteration:
                return
            except Exception as e:
                text = repr(e)
                _print('\n\n{}[‼️] Error: {} in {}'.format(RED, repr(e), BLACK))
                _print("\033[F" * (text.count('\n') + 3 + len(text)//width))

    threads = [threading.Thread(target=target, daemon=True) for i in range(8)]
    for i in threads:
        print("{}[🟢] Starting thread {}{}".format(GREEN, i, BLACK))
        i.start()

    def status():
        while True:
            c = len([i for i in threads if i.is_alive()])
            status_print('[👍] {} threads are still living'.format(c))
            for thread in threads:
                if not thread.is_alive:
                    print('[💀] Thread "{}" is dead'.format(thread))
            time.sleep(1)

    status_thread = threading.Thread(target=status, daemon=True)
    status_thread.start()
    return threads


def joinurls(a: str, b: str) -> str:
    return url_normalize('{}/{}'.format(a, b))


class Crawler:
    def __init__(self, start_url: str, first_page: str, delay: float = DELAY) -> None:
        self.start_url = start_url
        self.delay = delay
        self.ensure_directories = True

        self._current_base = self.start_url
        self._pending_links = [(self.start_url, first_page)]
        self._finished: Set[str] = set()
        self._cwd, _ = urltopathcomponents(self.start_url)

    def _extendlinksof(self, url: str) -> None:
        req = requests.get(url)
        content = req.text
        soup = bs(content, 'html.parser')
        links = []
        for i in soup.findAll('a'):
            pair = (self._current_base, ref := i.get("href"))
            if not ref:
                continue
            normalized = normalize(*pair)
            if ref and normalized not in self._finished:
                links.append(pair)
            elif pair in self._finished:
                print("{}[⚠️] Skipping {} because it was already gotten{}".format(YELLOW, pair, BLACK))
        # links = [(self._current_base, link) for i in soup.find_all('a') if (ref := i.get('href')) and (self._current_base, (link := ref)) not in self._finished]
        self._pending_links.extend(links)
        print('{}[✅] Adding {} links to queue. There are {} links pending{}'.format(BLACK, len(links), len(self._pending_links), BLACK))

    def __iter__(self) -> 'Crawler':
        return self

    def __next__(self) -> Optional[urltolocalcorrespondance]:
        if len(self._pending_links) == 0:
            return None
        base, location = self._pending_links.pop(0)
        self._current_base = base
        self._finished.add(normalize(base, location))
        absolute = normalize(self._current_base, location)
        parsed = urllib.parse.urlparse(absolute)

        self._extendlinksof(absolute)

        components = urltopathcomponents(parsed.path)
        if self.ensure_directories and components.directory:
            try:
                os.makedirs(components.directory)
            except FileExistsError:
                pass
                # do not create if already exists
                # print("Already exists! {}".format(components.directory))
        return urltolocalcorrespondance(components, absolute)


def log(*msgs):
    print(*msgs)


def normalize(base: str, url: str) -> str:
    # check for root url
    if url.startswith('/'):
        # if the url is an absolute path glom it to the end
        # of the host using urljoin
        return urllib.parse.urljoin(base, url)

    # check for absolute instead of relative url
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme:
        url
    else:
        url = str(url_normalize(joinurls(base, url)))

    # remove any fragments
    scheme, netloc, path, params, query, _ = urllib.parse.urlparse(url)
    result = urllib.parse.ParseResult(scheme, netloc, path, params, query, '')
    return urllib.parse.urlunparse(result)


def getopts():
    ap = argparse.ArgumentParser()
    ap.add_argument('-b', '--baseurl')
    ap.add_argument('-p', '--firstpage')
    ap.add_argument('-o', '--overwrite', action='store_true')
    return ap.parse_args()


def main():
    options = getopts()
    base, page = options.baseurl, options.firstpage
    base = base.rstrip('/')

    # for site, content in downloadsite(base, page, overwrite=options.overwrite):
    # print("Downloading site {}".format(site))
    downloadsite(base, page, overwrite=options.overwrite)
    input("Waiting... ")


if __name__ == '__main__':
    raise SystemExit(main())
