# Playing a YouTube video: ask YouTube's own API ("InnerTube", the one its
# apps use) for the video's streams, and pick one SnakeyOS can decode: format
# 18, an MP4 with H.264 Baseline video (360p) and AAC sound in one file.
#
#   url, title = youtube.stream("dQw4w9WgXcQ")     -> a URL the player can open
#
# YouTube changes this API now and then, and for some videos it only gives
# addresses that need its JavaScript player to unscramble. Several client
# identities are tried in turn; if none gives a plain address, the error
# says so. (Format 18 is the only one with H.264 Baseline: the others use
# the Main/High profiles, VP9 or AV1, which SnakeyOS cannot decode yet.)
import json

API = "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
CLIENTS = [  # (name, version, extra context, User-Agent)
    ("ANDROID_VR", "1.60.19", {"deviceMake": "Oculus", "deviceModel": "Quest 3", "androidSdkVersion": 32,
                                "osName": "Android", "osVersion": "12L"},
     "com.google.android.apps.youtube.vr.oculus/1.60.19 (Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip"),
    ("IOS", "20.10.4", {"deviceMake": "Apple", "deviceModel": "iPhone16,2", "osName": "iPhone", "osVersion": "18.3.2.22D82"},
     "com.google.ios.youtube/20.10.4 (iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X;)"),
    ("TVHTML5_SIMPLY_EMBEDDED_PLAYER", "2.0", {}, "Mozilla/5.0"),
]
PLAYABLE = (18,)          # MP4: H.264 Baseline + AAC


class Unplayable(Exception):
    pass


def _player(video_id, client):
    from urllib import request
    name, version, extra, agent = client
    ctx = {"clientName": name, "clientVersion": version, "hl": "es", "gl": "ES"}
    ctx.update(extra)
    body = {"context": {"client": ctx}, "videoId": video_id, "contentCheckOk": True, "racyCheckOk": True}
    if name.startswith("TVHTML5"):
        body["context"]["thirdParty"] = {"embedUrl": "https://www.youtube.com/"}
    req = request.Request(API, json.dumps(body).encode(),
                          {"Content-Type": "application/json", "User-Agent": agent, "X-Goog-Api-Format-Version": "2"},
                          "POST")
    r = request.urlopen(req, timeout=30)
    return json.loads(r.read())


def stream(video_id):
    """(url, title) of a stream of the video that SnakeyOS can play."""
    reasons = []
    for client in CLIENTS:
        try:
            data = _player(video_id, client)
        except Exception as e:
            reasons.append("%s: %s" % (client[0], e))
            continue
        status = data.get("playabilityStatus", {})
        if status.get("status") not in (None, "OK"):
            reasons.append("%s: %s" % (client[0], status.get("reason") or status.get("status")))
            continue
        title = data.get("videoDetails", {}).get("title", video_id)
        formats = data.get("streamingData", {}).get("formats", [])
        for f in formats:
            if f.get("itag") in PLAYABLE and f.get("url"):
                return f["url"], title
        reasons.append("%s: sin un formato H.264 Baseline con direccion directa" % client[0])
    raise Unplayable("YouTube no dio un video que SnakeyOS pueda reproducir (%s)" % "; ".join(reasons))
