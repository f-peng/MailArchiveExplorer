import pytest

from mail_archive_explorer.ui.html_sanitizer import csp, sanitize_html


@pytest.mark.parametrize("src", [
    '<link rel="preconnect" href="http://evil.test">',
    '<LINK REL=preconnect HREF=http://evil.test>',
    '<link/rel=preconnect/href="http://evil.test">',
    '<  link rel=dns-prefetch href=//evil.test>',
    '<base href="http://evil.test/">',
    '<meta http-equiv="refresh" content="0;url=http://evil.test">',
    '<!-- <link rel=preconnect href=http://evil.test> -->',
    '<!--[if mso]><link rel=preconnect href=http://evil.test><![endif]-->',
    '<style><link rel=preconnect href=http://evil.test></style>',
    '<textarea><link rel=preconnect href=http://evil.test></textarea>',
    '<title><link rel=preconnect href=http://evil.test></title>',
    '<script>x="<link rel=preconnect href=http://evil.test>"</script>',
    '<svg><link rel=preconnect href=http://evil.test /></svg>',
    '<a href="x"><link rel=preconnect href=http://evil.test></a>',
])
def test_aucun_link_base_meta_ne_survit(src):
    import re
    out = sanitize_html(f"<html><head>{src}</head><body>x</body></html>")
    assert not re.search(r"<[\s/]*(link|base)\b", out, re.I), out
    metas = re.findall(r"<[\s/]*meta\b[^>]*>", out, re.I)
    assert len(metas) == 1 and "Content-Security-Policy" in metas[0]      # seule notre meta CSP


def test_elements_actifs_supprimes_avec_contenu():
    out = sanitize_html('<p>a</p><script>alert(1)</script><iframe src="http://x">sec</iframe>'
                        '<object data="http://x"><p>o</p></object><embed src=x><p>b</p>')
    assert "script" not in out.lower() and "iframe" not in out.lower() and "<object" not in out.lower() and "<embed" not in out.lower()
    assert "<p>a</p>" in out and "<p>b</p>" in out and "alert" not in out


def test_contenu_et_mise_en_forme_conserves():
    src = '<!DOCTYPE html><html><body><p style="color:red">Café &amp; crème &eacute; &#233;</p><img src="data:image/png;base64,AAAA"><a href="http://x">lien</a></body></html>'
    out = sanitize_html(src)
    assert out.startswith("<!DOCTYPE html>")                          # le doctype précède le CSP
    assert 'style="color:red"' in out and "Café &amp; crème &eacute; &#233;" in out
    assert 'src="data:image/png;base64,AAAA"' in out and '<a href="http://x">lien</a>' in out


def test_csp_images_distantes():
    assert "img-src data:;" in csp(False) and "http:" not in csp(False)
    assert "img-src data: http: https:" in csp(True)
    assert "default-src 'none'" in csp(False) and "form-action 'none'" in csp(False)


def test_html_vide_ou_malforme_ne_leve_pas():
    for s in ("", "<", "<<<>>>", "<link", "&", "<p", "x" * 10000, "<div" * 500):
        out = sanitize_html(s)
        assert "Content-Security-Policy" in out
