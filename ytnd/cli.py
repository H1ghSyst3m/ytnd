# ytnd/cli.py
"""
Simple CLI frontend for YTND. Can be used in cronjobs and automated tasks.
"""
import argparse, sys
from .downloader import Downloader
from .utils import logger

def main():
    p = argparse.ArgumentParser(description="YTN Downloader – CLI")
    p.add_argument("urls", nargs="+", help="YouTube links or text files with URLs")
    p.add_argument("-u", "--user", default="local", help="user ID (folder name)")
    p.add_argument("-w", "--workers", type=int, default=4, help="parallel threads")
    args = p.parse_args()

    all_urls = []
    for item in args.urls:
        if item.endswith(".txt"):
            try:
                with open(item, encoding="utf-8") as f:
                    all_urls.extend(l.strip() for l in f if l.strip())
            except IOError as e:
                logger.error("Cannot read %s: %s", item, e)
        else:
            all_urls.append(item)

    if not all_urls:
        logger.error("No valid URLs provided.")
        sys.exit(1)

    dl = Downloader(args.user)
    dl.add_urls(all_urls)
    dl.run(workers=args.workers)

if __name__ == "__main__":
    main()
