import requests
import xml.etree.ElementTree as ET
import os
import re
import sys
import json
from typing import Optional, Tuple
import getpass


class TableauClient:
    def __init__(self, server: str, api_version: str, site: str, verify_ssl: bool = True):
        self.server = server.rstrip("/")
        self.api_version = api_version
        self.site = site
        self.verify_ssl = verify_ssl
        self.token: Optional[str] = None
        self.site_id: Optional[str] = None

    def sign_in(self, username: str, password: str) -> Tuple[str, str]:
        url = f"{self.server}/api/{self.api_version}/auth/signin"
        body = f'<tsRequest><credentials name="{username}" password="{password}"><site contentUrl="{self.site}"/></credentials></tsRequest>'
        headers = {"Content-Type": "application/xml", "Accept": "application/xml"}
        response = requests.post(url, data=body.encode("utf-8"), headers=headers, verify=self.verify_ssl, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        creds, site_el = None, None
        for el in root.iter():
            tag = el.tag.split('}')[-1]
            if tag == 'credentials': creds = el
            if tag == 'site': site_el = el
        if creds is None or 'token' not in creds.attrib or site_el is None or 'id' not in site_el.attrib:
            raise RuntimeError("Failed to parse token/site_id from XML")
        self.token = creds.attrib['token']
        self.site_id = site_el.attrib['id']
        return self.token, self.site_id

    def sign_out(self):
        if self.token:
            url = f"{self.server}/api/{self.api_version}/auth/signout"
            try:
                requests.post(url, headers={"X-Tableau-Auth": self.token}, verify=self.verify_ssl, timeout=10)
            except Exception:
                pass


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', '_', name)


def load_config(config_path: str = "config.json") -> dict:
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    try:
        config = load_config()
    except FileNotFoundError:
        print("❌ Файл config.json не найден.")
        sys.exit(1)

    tableau_cfg = config.get("tableau", {})
    server = tableau_cfg.get("server")
    api_version = tableau_cfg.get("api_version")
    site = tableau_cfg.get("site", "")
    verify_ssl = tableau_cfg.get("verify_ssl", True)

    auth_cfg = tableau_cfg.get("auth", {})
    username = auth_cfg.get("username", "")
    password = auth_cfg.get("password", "")

    # Берем LUID напрямую из конфига
    project_luid = config.get("project_luid")
    download_path = config.get("download_path")

    if not project_luid:
        print("❌ Укажите project_luid в config.json (его можно взять из базы данных)")
        sys.exit(1)

    if not password:
        password = getpass.getpass("🔑 Введите пароль: ")

    client = TableauClient(server, api_version, site, verify_ssl)
    try:
        token, site_id = client.sign_in(username, password)
        print(f"✅ Аутентификация успешна. Site ID: {site_id}")
    except Exception as e:
        print(f"❌ Ошибка аутентификации: {e}")
        sys.exit(1)

    print(f"📌 Используем LUID проекта: {project_luid}")

    # Скачивание книг
    headers = {"X-Tableau-Auth": client.token, "Accept": "application/xml"}
    all_workbooks = []
    page = 1
    page_size = 100
    ns = {'t': 'http://tableau.com/api'}

    while True:
        workbooks_url = f"{server}/api/{api_version}/sites/{client.site_id}/workbooks?pageSize={page_size}&pageNumber={page}"
        print(f"📡 Запрос страницы {page}...")
        response = requests.get(workbooks_url, headers=headers, verify=verify_ssl, timeout=60)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        for wb in root.findall('.//t:workbook', ns):
            wb_id = wb.get('id')
            wb_name = wb.get('name')
            project_el = wb.find('t:project', ns)

            if project_el is not None and project_el.get('id') == project_luid:
                all_workbooks.append((wb_id, wb_name))

        if len(root.findall('.//t:workbook', ns)) < page_size:
            break
        page += 1

    if not all_workbooks:
        print(f"ℹ️ В проекте не найдено книг.")
        client.sign_out()
        sys.exit(0)

    print(f"📚 Найдено книг: {len(all_workbooks)}")
    os.makedirs(download_path, exist_ok=True)

    for wb_id, wb_name in all_workbooks:
        print(f"⬇️ Скачивание: {wb_name}")
        download_url = f"{server}/api/{api_version}/sites/{client.site_id}/workbooks/{wb_id}/content"
        try:
            resp = requests.get(download_url, headers={"X-Tableau-Auth": client.token}, stream=True, verify=verify_ssl)
            resp.raise_for_status()
        except Exception as e:
            print(f"   ❌ Ошибка скачивания: {e}")
            continue

        ext = '.twbx' if '.twbx' in resp.headers.get('content-disposition', '') else '.twb'
        file_path = os.path.join(download_path, f"{sanitize_filename(wb_name)}{ext}")

        with open(file_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"   ✅ Сохранено: {file_path}")

    print("🎉 Готово! Все книги выгружены.")
    client.sign_out()


if __name__ == "__main__":
    main()