from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = APP_ROOT / "static"
TEMPLATE_ROOT = APP_ROOT / "templates"


def test_install_prompt_is_rendered_and_shared_by_both_layouts(app):
    client = app.test_client()

    login_page = client.get("/auth/login")
    assert login_page.status_code == 200
    assert b'id="faida-install-backdrop"' in login_page.data
    assert b'/static/js/faida-install.js' in login_page.data

    include = '{% include "includes/pwa_install_prompt.html" %}'
    assert include in (TEMPLATE_ROOT / "layouts" / "base.html").read_text()
    assert include in (TEMPLATE_ROOT / "layouts" / "base-fullscreen.html").read_text()


def test_install_script_covers_supported_mobile_install_flows():
    script = (STATIC_ROOT / "js" / "faida-install.js").read_text()

    assert "beforeinstallprompt" in script
    assert "appinstalled" in script
    assert "display-mode: standalone" in script
    assert "android-app://" in script
    assert "iphone|ipad|ipod" in script
    assert "faida-install-dismissed" in script


def test_manifest_and_service_worker_support_installation(app):
    client = app.test_client()

    manifest_response = client.get("/static/manifest.json")
    manifest = manifest_response.get_json()
    assert manifest_response.status_code == 200
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert {icon["sizes"] for icon in manifest["icons"]} >= {"192x192", "512x512"}

    worker_response = client.get("/sw.js")
    worker = worker_response.get_data(as_text=True)
    assert worker_response.status_code == 200
    assert worker_response.headers["Service-Worker-Allowed"] == "/"
    assert "faida-install.js" in worker
