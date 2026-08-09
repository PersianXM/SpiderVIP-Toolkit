#!/usr/bin/env python3
"""
Frequency Manager — SpiderVIP TP / frequency sync web app.

Workflow:
  1. Pick a satellite already present in the receiver (dropdown).
  2. Enter a LyngSat (or compatible) page URL as the external source.
  3. App scrapes the source frequencies.
  4. A side-by-side comparison table shows which carriers exist on both sides
     and which exist only on one side.
  5. User ticks the carriers to import.
  6. Selected carriers are appended to the chosen satellite (as TP N+1, N+2, …)
     preserving the receiver XML structure.
  7. The full, valid receiver database is offered for download.

Run from this package directory:
    python app.py
Then open http://127.0.0.1:5000
"""

import io
import os
import datetime


from flask import (
    Flask, render_template, request, jsonify, send_file, session
)

import scraper
import receiver
import deploy

app = Flask(__name__)
app.secret_key = "lyngsat-web-secret"
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


@app.after_request
def _no_cache_html(response):
    if response.content_type and "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-store"
    return response


def _db_path():
    """Active receiver database: a live copy if one was pulled, else bundled."""
    path = session.get("receiver_db_path", "")
    if path and os.path.exists(path):
        return path
    return receiver.DATA_FILE


@app.route("/")
def index():
    return render_template("index.html")


def _creds_hint(host):
    return (
        f"IP هدف: {host or '—'} — رسیور باید روشن و در همان شبکه باشد؛ "
        "در حالت کنسول ابتدا اتصال را در صفحهٔ اصلی ذخیره کنید. "
        "اگر FTP بسته است ولی Telnet باز است، واکشی از Telnet انجام می‌شود."
    )


def _try_pull_live(host=None, user=None, password=None):
    """Best-effort: pull the live receiver DB and cache it in the session.

    Returns the local path on success, or None on failure. Keeping the whole
    flow (dropdown → comparison → apply → push) anchored to the SAME live data
    is what guarantees that removals actually match real carriers on the device.
    """
    host = (host or "").strip() or deploy.DEFAULT_HOST
    user = (user or "").strip() or deploy.DEFAULT_USER
    password = deploy.DEFAULT_PASS if password in (None, "") else password
    try:
        result = deploy.download_receiver_db(host, user, password)
        xml_bytes = result["data"]
        live_path = os.path.join(OUTPUT_DIR, "live_receiver_data.xml")
        with open(live_path, "wb") as fh:
            fh.write(xml_bytes)
        # Validate it parses before trusting it.
        receiver.list_satellites(live_path)
        session["receiver_db_path"] = live_path
        session["receiver_db_transport"] = result.get("transport", "")
        return live_path
    except Exception:  # noqa: BLE001
        return None


@app.route("/satellites")
def satellites_route():
    """Return the list of satellites available in the receiver.

    Auto-pulls the live device DB on first load (best effort) so the dropdown
    counts and the later comparison match the receiver exactly.
    Optional query: host, user, password (from Console shared connection).
    """
    try:
        cached = session.get("receiver_db_path", "")
        if not (cached and os.path.exists(cached)):
            host = (request.args.get("host") or "").strip() or None
            user = (request.args.get("user") or "").strip() or None
            password = request.args.get("password")
            _try_pull_live(host=host, user=user, password=password)
        db = _db_path()
        source = "live" if session.get("receiver_db_path") and os.path.exists(
            session.get("receiver_db_path", "")) else "bundled"
        return jsonify({
            "ok": True,
            "satellites": receiver.list_satellites(db),
            "source": source,
            "transport": session.get("receiver_db_transport") or None,
        })
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500



@app.route("/load_receiver", methods=["POST"])
def load_receiver_route():
    """Pull live satellites.xml from the receiver (FTP, else Telnet) and use it.

    Expected JSON: { "host": ..., "user": ..., "password": ... }
    """

    data = request.get_json(silent=True) or {}
    host = (data.get("host") or deploy.DEFAULT_HOST).strip()
    user = (data.get("user") or deploy.DEFAULT_USER).strip()
    password = data.get("password")
    if password is None or password == "":
        password = deploy.DEFAULT_PASS

    if not host:
        return jsonify({
            "ok": False,
            "error": "IP رسیور خالی است.",
            "hint": "در کنسول ابتدا اتصال را ذخیره کنید؛ در حالت مستقل IP را وارد کنید.",
        }), 400

    try:
        result = deploy.download_receiver_db(host, user, password)
        xml_bytes = result["data"]
        transport = result.get("transport", "ftp")
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "ok": False,
            "error": f"واکشی زنده از رسیور ناموفق بود: {exc}",
            "hint": _creds_hint(host),
            "host": host,
        }), 502

    live_path = os.path.join(OUTPUT_DIR, "live_receiver_data.xml")
    with open(live_path, "wb") as fh:
        fh.write(xml_bytes)

    # Validate it parses and get the satellite list.
    try:
        sats = receiver.list_satellites(live_path)
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "ok": False,
            "error": f"فایل دریافت‌شده از رسیور معتبر نبود: {exc}",
        }), 502

    session["receiver_db_path"] = live_path
    session["receiver_db_transport"] = transport
    return jsonify({
        "ok": True,
        "host": host,
        "source": "live",
        "transport": transport,
        "satellites": sats,
    })



@app.route("/scrape", methods=["POST"])
def scrape_route():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    sat_index = data.get("sat_index")

    if not url:
        return jsonify({"ok": False, "error": "لطفاً یک لینک وارد کنید."}), 400
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url

    try:
        rows = scraper.scrape(url)
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "ok": False,
            "error": f"واکشی صفحه ناموفق بود: {exc}",
        }), 502

    if not rows:
        return jsonify({
            "ok": False,
            "error": "هیچ اطلاعات فرکانسی پیدا نشد. ساختار صفحه ممکن است تغییر کرده باشد.",
        }), 404

    text = scraper.rows_to_text(rows)

    # Save a copy on disk with a timestamped name.
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"frequencies_{stamp}.txt"
    with open(os.path.join(OUTPUT_DIR, fname), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")

    session["last_text"] = text

    # Build the comparison against the chosen receiver satellite.
    comparison = None
    sat_info = None
    comparison_error = None
    if sat_index is not None and sat_index != "":
        try:
            idx = int(sat_index)
            sat = receiver.get_satellite(idx, _db_path())
            sat_info = {

                "index": idx,
                "name": sat["name"],
                "position": sat["position"],
                "count": len(sat["transponders"]),
            }
            cmp = scraper.compare_frequencies(sat["transponders"], rows)
            comparison = {
                "receiver_name": sat["name"],
                "receiver_position": sat["position"],
                "rows": cmp["rows"],
                "stats": cmp["stats"],
            }
        except Exception as exc:  # noqa: BLE001 - comparison is best-effort
            comparison = None
            comparison_error = str(exc)

    return jsonify({
        "ok": True,
        "count": len(rows),
        "rows": rows,
        "text": text,
        "saved_as": fname,
        "comparison": comparison,
        "satellite": sat_info,
        "comparison_error": comparison_error,
    })


@app.route("/apply", methods=["POST"])
def apply_route():
    """Add and/or remove carriers on a satellite and return the new DB.

    Expected JSON:
        {
          "sat_index": <int>,
          "add":    [ {freq,pol,sr,fec}, ... ],   # from LyngSat
          "remove": [ {freq,pol,sr,fec}, ... ]    # existing receiver carriers
        }
    """
    data = request.get_json(silent=True) or {}
    sat_index = data.get("sat_index")
    add_rows = data.get("add") or []
    remove_rows = data.get("remove") or []

    if sat_index is None or sat_index == "":
        return jsonify({"ok": False, "error": "ماهواره‌ای انتخاب نشده است."}), 400
    if not add_rows and not remove_rows:
        return jsonify({
            "ok": False,
            "error": "هیچ تغییری انتخاب نشده است (نه افزودن و نه حذف).",
        }), 400

    # CRITICAL: always edit the receiver's *current live* database, not a stale
    # bundled/factory copy. Otherwise removals won't match the real carriers and
    # the pushed file appears "unchanged" on the device. If receiver creds are
    # provided (default host/root/root), re-pull the live DB right now and use it
    # as the edit base so what we push is guaranteed to be the device's own data.
    host = (data.get("host") or deploy.DEFAULT_HOST).strip()
    user = (data.get("user") or deploy.DEFAULT_USER).strip()
    password = data.get("password")
    if password is None or password == "":
        password = deploy.DEFAULT_PASS

    base_path = _db_path()
    live_note = None
    try:
        pulled = deploy.download_receiver_db(host, user, password)
        xml_bytes = pulled["data"]
        live_path = os.path.join(OUTPUT_DIR, "live_receiver_data.xml")
        with open(live_path, "wb") as fh:
            fh.write(xml_bytes)
        session["receiver_db_path"] = live_path
        session["receiver_db_transport"] = pulled.get("transport", "")
        base_path = live_path
        via = pulled.get("transport", "?")
        live_note = (
            f"پایگاه‌داده‌ی زنده‌ی رسیور مبنای ویرایش قرار گرفت (از طریق {via})."
        )
    except Exception as exc:  # noqa: BLE001
        # Fall back to whatever we have, but tell the user it may not match.
        live_note = (f"هشدار: واکشی زنده‌ی رسیور ممکن نشد ({exc}); از نسخه‌ی "
                     f"موجود استفاده شد — ممکن است با دستگاه هم‌خوان نباشد.")

    try:
        idx = int(sat_index)
        result = receiver.apply_changes(idx, add_rows=add_rows,
                                        remove_rows=remove_rows,
                                        data_file=base_path)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"خطا در ساخت خروجی: {exc}"}), 500


    # Persist the generated database so it can be downloaded / pushed.
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name = f"receiver_data_{stamp}.xml"
    out_path = os.path.join(OUTPUT_DIR, out_name)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(result["xml"])

    session["last_xml_path"] = out_path

    return jsonify({
        "ok": True,
        "sat_name": result["sat_name"],
        "before": result["before"],
        "added": result["added"],
        "removed": result["removed"],
        "after": result["after"],
        "saved_as": out_name,
        "live_note": live_note,
    })



@app.route("/send_to_receiver", methods=["POST"])
def send_to_receiver_route():
    """Push the last generated database to the receiver (FTP or Telnet) + WebIF.

    Uploads the edited satellites.xml onto the live DB and calls the WebIF
    /web/servicelistreload so the change is committed into the box's binary
    store (live_prog) — persistent, no reboot needed. After reload, Motor/USALS
    is restored from channels ``motor_profile.json`` and/or a pre-reload
    ``live_prog`` backup (same approach as Favorite Apply).

    Expected JSON (all optional except that an export must have run first):
        { "host": "192.168.100.102", "user": "root", "password": "root",
          "workspace": optional channels workspace path }
    """

    data = request.get_json(silent=True) or {}
    host = (data.get("host") or deploy.DEFAULT_HOST).strip()
    user = (data.get("user") or deploy.DEFAULT_USER).strip()
    password = data.get("password")
    if password is None or password == "":
        password = deploy.DEFAULT_PASS
    workspace = (data.get("workspace") or "").strip() or None

    path = session.get("last_xml_path", "")
    if not path or not os.path.exists(path):
        return jsonify({
            "ok": False,
            "error": "ابتدا باید فرکانس‌ها را کپی/خروجی بگیرید (مرحله ۶).",
        }), 400

    with open(path, "rb") as fh:
        xml_bytes = fh.read()

    try:
        steps = deploy.send_to_receiver(
            xml_bytes,
            host=host,
            user=user,
            password=password,
            workspace=workspace,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "ok": False,
            "error": f"انتقال به رسیور ناموفق بود: {exc}",
            "hint": _creds_hint(host),
            "host": host,
        }), 502

    return jsonify({"ok": True, "host": host, "steps": steps})


@app.route("/download_xml")
def download_xml_route():
    path = session.get("last_xml_path", "")
    if not path or not os.path.exists(path):
        return "No generated file available. Please export first.", 404
    return send_file(
        path,
        mimetype="application/xml",
        as_attachment=True,
        download_name="satellites.xml",
    )



@app.route("/download", methods=["POST"])
def download_route():
    """Download the currently posted text as a .txt file."""
    text = request.form.get("text", "")
    if not text:
        text = session.get("last_text", "")
    buf = io.BytesIO(text.encode("utf-8"))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="text/plain",
        as_attachment=True,
        download_name="frequencies.txt",
    )


if __name__ == "__main__":
    print("Frequency Manager running at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
