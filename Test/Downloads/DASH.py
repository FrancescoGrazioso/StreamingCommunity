# 29.07.25
# ruff: noqa: E402

import os
import sys


# Fix import
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(src_path)


from StreamingCommunity.utils import config_manager, start_message
from StreamingCommunity.core.downloader import DASH_Downloader


start_message()
conf_extension = config_manager.config.get("M3U8_CONVERSION", "extension")


mpd_url = 'https://akm.dplus.eu.prd.media.max.com/2cbf74bc-4277-4b01-aed0-2440a2062171/dash.mpd?manifest-params=r1%7CmNgzUcu78dKKRcgCKf0xGgG9S7DD0Y9Luo66G0i9jPg%3D%7CZi5hdWRpb1RyYWNrPWJnJTdDcHJvZ3JhbSZmLmF1ZGlvVHJhY2s9Y3MlN0Nwcm9ncmFtJmYuYXVkaW9UcmFjaz1lbi1VUyU3Q3Byb2dyYW0mZi5hdWRpb1RyYWNrPWVzLUVTJTdDcHJvZ3JhbSZmLmF1ZGlvVHJhY2s9ZnItRlIlN0Nwcm9ncmFtJmYuYXVkaW9UcmFjaz1odSU3Q3Byb2dyYW0mZi5hdWRpb1RyYWNrPWl0JTdDcHJvZ3JhbSZmLmF1ZGlvVHJhY2s9bHQlN0Nwcm9ncmFtJmYuYXVkaW9UcmFjaz1wbCU3Q3Byb2dyYW0mZi5hdWRpb1RyYWNrPXJ1JTdDcHJvZ3JhbSZmLm1lcmdlUGVyaW9kcz10cnVlJmYudmlkZW9Db2RlYz1hdmMmZi52aWRlb0R5bmFtaWNSYW5nZT1zZHImZi52aWRlb01heEhlaWdodD01NDAmZi52aWRlb01heFdpZHRoPTcyMCZyLmR1cmF0aW9uPTI2MjcuMjAwMDAwJnIua2V5bW9kPTImci5tYWluPTAmci5tYW5pZmVzdD0yY2JmNzRiYy00Mjc3LTRiMDEtYWVkMC0yNDQwYTIwNjIxNzElMkYzXzI3YjNlZC5tcGQlN0NwcmQtd2JkLWVtZWEtdm9k&rtype=r&x-wbd-tenant=dplus&x-wbd-user-home-market=emea'
mpd_headers = {}
license_url = 'https://busy.any-any.prd.api.discomax.com/drm-proxy/any/drm-proxy/drm/license/play-ready?drmKeyVersion=1&auth=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHBpcmF0aW9uVGltZSI6IjIwMjYtMDEtMzBUMjM6MTk6NTcuMjQxMTcwOTg5WiIsImVkaXRJZCI6IjM1Y2NmYzZiLTliOGItNGE3MS05YmNjLWU1YjhjZTM4YmY0NSIsImNvbnRlbnRJZCI6IjM1Y2NmYzZiLTliOGItNGE3MS05YmNjLWU1YjhjZTM4YmY0NSIsImFwcEJ1bmRsZSI6ImRwbHVzIiwicGxhdGZvcm0iOiJ3ZWIiLCJtYWtlIjoiZGVza3RvcCIsIm1vZGVsIjoiZGVza3RvcCIsImJyb3dzZXIiOiJNaWNyb3NvZnQgRWRnZSAxNDQuMC4wLjAiLCJ1c2VySWQiOiJVU0VSSUQ6Ym9sdDpmYjNkZmU4NS1jNTU2LTQxNGEtOTgxZC02NWVkM2Y4YTY3ZjkiLCJwcm9maWxlSWQiOiJQUk9GSUxFSURhMWU2M2RjOC01ZWQ0LTQ2OTctOGFjNS0xOGQ5YTE2N2E5MTQiLCJkZXZpY2VJZCI6IjllZTNiYjViLTE2MzctNDI3Yy1iYjM0LTFjNzgxZTBkOGI0YSIsInNzYWkiOnRydWUsInN0cmVhbVR5cGUiOiJ2b2QiLCJoZWFydGJlYXRFbmFibGVkIjpmYWxzZSwicGxheWJhY2tTZXNzaW9uSWQiOiI1OTljMDc1Mi1iYzMyLTQ2NjUtYWE4OS05NTc5NjRlODM3YTkiLCJ0cmFjZUlkIjoiMWVmN2NkZTkwNmMxMzY5ZmVmMjlkZGI1NDFiY2YxNDMifQ.BeEFiUsCTMc87soVj8G8kOg0t-DNZb6_TP4IvDWcGM0&x-wbd-tenant=dplus&x-wbd-user-home-market=emea'
license_headers = {}
license_key = None

dash_process = DASH_Downloader(
    mpd_url=mpd_url,
    mpd_headers=mpd_headers,
    license_url=license_url,
    license_headers=license_headers,
    output_path=fr".\Video\Prova.{conf_extension}",
    drm_preference="playready"
)

out_path, need_stop = dash_process.start()
print(f"Output path: {out_path}, Need stop: {need_stop}")