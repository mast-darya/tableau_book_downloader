import requests
import xml.etree.ElementTree as ET
import os
import re
import sys
import json
from typing import Optional, Tuple, List
from urllib.parse import quote

# ---------- Класс TableauClient (без изменений) ----------
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
        creds = None
        site_el = None
        for el in root.iter():
            tag = el.tag.split('}')[-1]
            if tag == 'credentials':
                creds = el
            if tag == 'site':
                site_el = el
        if creds is None or 'token' not in creds.attrib or site_el is None or 'id' not in site_el.attrib:
            raise RuntimeError("Failed to parse token/site_id from XML")
        self.token = creds.attrib['token']
        self.site_id = site_el.attrib['id']
        return self.token, self.site_id

    def sign_in_with_pat(self, pat_name: str, pat_secret: str) -> Tuple[str, str]:
        url = f"{self.server}/api/{self.api_version}/auth/signin"
        body = f'''<tsRequest>
  <credentials personalAccessTokenName="{pat_name}" personalAccessTokenSecret="{pat_secret}">
    <site contentUrl="{self.site}"/>
  </credentials>
</tsRequest>'''
        headers = {"Content-Type": "application/xml", "Accept": "application/xml"}
        response = requests.post(url, data=body.encode("utf-8"), headers=headers, verify=self.verify_ssl, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        creds = None
        site_el = None
        for el in root.iter():
            tag = el.tag.split('}')[-1]
            if tag == 'credentials':
                creds = el
            if tag == 'site':
                site_el = el
        if creds is None or 'token' not in creds.attrib or site_el is None or 'id' not in site_el.attrib:
            raise RuntimeError("Failed to parse token/site_id from XML")
        self.token = creds.attrib['token']
        self.site_id = site_el.attrib['id']
        return self.token, self.site_id

    def sign_out(self):
        if self.token:
            url = f"{self.server}/api/{self.api_version}/auth/signout"
            headers = {"X-Tableau-Auth": self.token}
            try:
                requests.post(url, headers=headers, verify=self.verify_ssl, timeout=10)
            except Exception:
                pass
            self.token = None
            self.site_id = None
# ---------------------------------------------------------

# ---------- Вспомогательные функции ----------
def extract_project_id_from_url(url: str) -> str:
    match = re.search(r'/projects/(\d+)', url)
    if match:
        return match.group(1)
    raise ValueError("Не удалось извлечь project_id из URL")

def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', '_', name)

def load_config(config_path: str = "config.json") -> dict:
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)
# ---------------------------------------------

def main():
    # 1. Загружаем конфиг
    try:
        config = load_config()
    except FileNotFoundError:
        print("❌ Файл config.json не найден в текущей папке.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка в формате config.json: {e}")
        sys.exit(1)

    tableau_cfg = config.get("tableau", {})
    server = tableau_cfg.get("server")
    api_version = tableau_cfg.get("api_version")
    site = tableau_cfg.get("site", "")
    verify_ssl = tableau_cfg.get("verify_ssl", True)

    auth_cfg = tableau_cfg.get("auth", {})
    auth_type = auth_cfg.get("type", "password")

    project_url = config.get("project_url")
    download_path = config.get("download_path")

    if not server or not api_version or not project_url or not download_path:
        print("❌ В config.json отсутствуют обязательные поля: server, api_version, project_url, download_path")
        sys.exit(1)

    # 2. Получаем логин и пароль (из конфига или интерактивно)
    username = auth_cfg.get("username", "")
    password = auth_cfg.get("password", "")

    # Если в конфиге нет пароля, запрашиваем интерактивно
    if auth_type == "password" and not password:
        import getpass
        username = input("👤 Введите имя пользователя: ") if not username else username
        password = getpass.getpass("🔑 Введите пароль: ")

    # 3. Извлекаем ID проекта
    project_id = extract_project_id_from_url(project_url)
    print(f"📁 Проект ID: {project_id}")

    # 4. Создаём клиент и аутентифицируемся
    client = TableauClient(server, api_version, site, verify_ssl)
    try:
        if auth_type == "password":
            token, site_id = client.sign_in(username, password)
        elif auth_type == "pat":
            pat_name = auth_cfg.get("pat_name")
            pat_secret = auth_cfg.get("pat_secret")
            if not pat_name or not pat_secret:
                print("❌ Для PAT укажите pat_name и pat_secret в config.json")
                sys.exit(1)
            token, site_id = client.sign_in_with_pat(pat_name, pat_secret)
        else:
            print(f"❌ Неподдерживаемый тип аутентификации: {auth_type}")
            sys.exit(1)
        print(f"✅ Аутентификация успешна. Site ID: {site_id}")
    except Exception as e:
        print(f"❌ Ошибка аутентификации: {e}")
        sys.exit(1)

    # 5. Запрашиваем список книг в проекте
    workbooks_url = f"{server}/api/{api_version}/sites/{site_id}/workbooks?filter=projectId:{project_id}"
    headers = {"X-Tableau-Auth": token, "Accept": "application/xml"}
    print(f"📡 Запрос списка книг...")
    try:
        response = requests.get(workbooks_url, headers=headers, verify=verify_ssl, timeout=60)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Ошибка получения списка книг: {e}")
        client.sign_out()
        sys.exit(1)

    # 6. Парсим XML
    try:
        root = ET.fromstring(response.content)
        workbooks = []
        for wb in root.findall('.//workbook'):
            wb_id = wb.get('id')
            wb_name = wb.get('name')
            if wb_id and wb_name:
                workbooks.append((wb_id, wb_name))
    except Exception as e:
        print(f"❌ Ошибка парсинга XML: {e}")
        print("Ответ сервера (первые 500 символов):")
        print(response.text[:500])
        client.sign_out()
        sys.exit(1)

    if not workbooks:
        print(f"ℹ️ В проекте с ID {project_id} не найдено книг.")
        client.sign_out()
        sys.exit(0)

    print(f"📚 Найдено книг: {len(workbooks)}")

    # 7. Создаём папку для загрузок
    os.makedirs(download_path, exist_ok=True)

    # 8. Скачиваем каждую книгу
    for wb_id, wb_name in workbooks:
        print(f"⬇️ Скачивание: {wb_name} (ID: {wb_id})")
        download_url = f"{server}/api/{api_version}/sites/{site_id}/workbooks/{wb_id}/content"
        try:
            resp = requests.get(download_url, headers={"X-Tableau-Auth": token}, stream=True, verify=verify_ssl)
            resp.raise_for_status()
        except Exception as e:
            print(f"   ❌ Ошибка скачивания: {e}")
            continue

        content_disposition = resp.headers.get('content-disposition', '')
        ext = '.twbx' if '.twbx' in content_disposition else '.twb'

        safe_name = sanitize_filename(wb_name)
        file_path = os.path.join(download_path, f"{safe_name}{ext}")

        with open(file_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"   ✅ Сохранено: {file_path}")

    print("🎉 Готово!")
    client.sign_out()

if __name__ == "__main__":
    main()