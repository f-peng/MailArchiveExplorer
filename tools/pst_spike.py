"""Spike PHASE 0 : exploration réelle d'un PST via pypff (libpff).

Usage : python -I tools/pst_spike.py <fichier.pst> [--dump-first N]

Ouvre le fichier en lecture seule, parcourt l'arborescence, lit pour chaque
message objet / expéditeur / dates / destinataires / corps texte, HTML, RTF /
en-têtes de transport, énumère les pièces jointes et lit leurs octets.
Affiche des compteurs, les erreurs rencontrées et le débit.
Ce script est un outil de diagnostic, pas le futur lecteur de production.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from collections import Counter

import pypff


def _safe(fn, errors: Counter, tag: str, default=None):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - spike : on compte tout
        errors[f"{tag}:{type(exc).__name__}"] += 1
        return default


def walk(folder, path=""):
    name = folder.get_name() or ""
    here = f"{path}/{name}" if path or name else "/"
    yield here, folder
    for i in range(folder.get_number_of_sub_folders()):
        yield from walk(folder.get_sub_folder(i), here)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pst")
    ap.add_argument("--dump-first", type=int, default=2)
    args = ap.parse_args()

    print(f"python {sys.version.split()[0]} | pypff/libpff {pypff.get_version()}")
    print("signature valide :", pypff.check_file_signature(args.pst))

    t_open = time.perf_counter()
    f = pypff.file()
    f.open(args.pst)  # lecture seule par construction (libpff n'écrit jamais)
    print(f"ouvert en {time.perf_counter() - t_open:.3f}s | taille={f.get_size()} octets"
          f" | content_type={f.get_content_type()} | chiffrement={f.get_encryption_type()}")

    errors: Counter = Counter()
    n_msg = n_att = n_att_bytes = 0
    n_other_items = 0
    n_plain = n_html = n_rtf = n_nobody = n_hdr = n_nodate = 0
    mime_counter: Counter = Counter()
    dumped = 0
    t0 = time.perf_counter()

    print("\n--- Dossiers ---")
    for path, folder in walk(f.get_root_folder()):
        cnt = folder.get_number_of_sub_messages()
        print(f"{cnt:6d}  {path}")
        for i in range(cnt):
            msg = _safe(lambda: folder.get_sub_message(i), errors, "get_sub_message")
            if msg is None:
                continue
            if not hasattr(msg, "get_subject"):
                # Contacts, rendez-vous... : libpff renvoie un pypff.item générique
                n_other_items += 1
                continue
            n_msg += 1
            subject = _safe(msg.get_subject, errors, "subject")
            sender = _safe(msg.get_sender_name, errors, "sender")
            date = _safe(msg.get_delivery_time, errors, "delivery") or _safe(
                msg.get_client_submit_time, errors, "submit")
            if date is None:
                n_nodate += 1
            plain = _safe(msg.get_plain_text_body, errors, "plain")
            html = _safe(msg.get_html_body, errors, "html")
            rtf = _safe(msg.get_rtf_body, errors, "rtf")
            hdr = _safe(msg.get_transport_headers, errors, "headers")
            n_plain += bool(plain)
            n_html += bool(html)
            n_rtf += bool(rtf)
            n_hdr += bool(hdr)
            n_nobody += not (plain or html or rtf)
            rcpts = []
            rec = _safe(lambda: msg.recipients, errors, "recipients")
            if rec is not None:
                for r in range(_safe(rec.get_number_of_recipients, errors, "nrcpt", 0)):
                    ent = _safe(lambda: rec.get_recipient(r), errors, "rcpt")
                    if ent is not None:
                        rcpts.append(ent)
            na = _safe(msg.get_number_of_attachments, errors, "natt", 0)
            for a in range(na):
                att = _safe(lambda: msg.get_attachment(a), errors, "get_attachment")
                if att is None:
                    continue
                size = _safe(att.get_size, errors, "att_size", 0) or 0
                data = _safe(lambda: att.read_buffer(size), errors, "att_read", b"") if size else b""
                n_att += 1
                n_att_bytes += len(data or b"")
                if size and len(data or b"") != size:
                    errors["att_short_read"] += 1
                if dumped < args.dump_first and data:
                    print(f"    PJ: {_safe(att.get_long_filename, errors, 'att_name')!r} "
                          f"size={size} sha256={hashlib.sha256(data).hexdigest()[:16]}")
                for rs in att.record_sets:
                    for ent in rs.entries:
                        if ent.entry_type == 0x370E:  # PR_ATTACH_MIME_TAG
                            mime_counter[_safe(ent.get_data_as_string, errors, "mime")] += 1
            if dumped < args.dump_first and (plain or html or rtf):
                dumped += 1
                print(f"  [msg] subject={subject!r} sender={sender!r} date={date}")
                print(f"        nb_recipients={len(rcpts)} nb_attachments={na}")
                for lbl, body in (("plain", plain), ("html", html), ("rtf", rtf)):
                    if body:
                        print(f"        {lbl}: {len(body)} octets, début={body[:70]!r}")
                if hdr:
                    print(f"        transport_headers: {hdr[:120]!r}")
    dt = time.perf_counter() - t0

    print("\n--- Résumé ---")
    print(f"messages={n_msg} avec_plain={n_plain} avec_html={n_html} avec_rtf={n_rtf} "
          f"sans_corps={n_nobody} avec_en-têtes_transport={n_hdr} sans_date={n_nodate}")
    print(f"pièces jointes={n_att} octets_lus={n_att_bytes} mimes={dict(mime_counter)}")
    print(f"items_non_message(contacts/rdv...)={n_other_items}")
    print(f"orphelins={f.get_number_of_orphan_items()}")
    print(f"erreurs={dict(errors)}")
    rate = n_msg / dt if dt else 0
    print(f"durée={dt:.3f}s  débit={rate:.0f} msg/s  {n_att_bytes / dt / 1e6 if dt else 0:.1f} Mo/s de PJ")
    f.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
