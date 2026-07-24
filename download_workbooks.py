import requests
import xml.etree.ElementTree as ET
import os
import re
import sys
import json
from typing import Optional, Tuple, List
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

    def get_project_luid_by_name(self, project_name: str) -> Optional[str]:
        url = f"{self.server}/api/{self.api_version}/sites/{self.site_id}/projects"
        headers = {"X-Tableau-Auth": self.token, "Accept": "application/xml"}
        response = requests.get(url, headers=headers, verify=self.verify_ssl, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        ns = {'t': 'http://tableau.com/api'}
        for proj in root.findall('.//t:project', ns):
            if proj.get('name') == project_name:
                return proj.get('id')
        return None

    def get_project_luid_by_numeric_id(self, numeric_id: int) -> Optional[str]:
        """
        Пытается найти проект по числовому ID, извлекая его из webpageUrl проекта.
        """
        url = f"{self.server}/api/{self.api_version}/sites/{self.site_id}/projects"
        headers = {"X-Tableau-Auth": self.token, "Accept": "application/xml"}
        response = requests.get(url, headers=headers, verify=self.verify_ssl, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        ns = {'t': 'http://tableau.com/api'}
        # Ищем project с webpageUrl, содержащим /projects/<число>
        pattern = re.compile(r'/projects/(\d+)')
        for proj in root.findall('.//t:project', ns):
            webpage_url = proj.get('webpageUrl', '')
            match = pattern.search(webpage_url)
            if match:
                proj_numeric_id = int(match.group(1))
                if proj_numeric_id == numeric_id:
                    return proj.get('id')
        return None
# ---------------------------------------------------------

# ---------- Вспомогательные функции ----------
def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', '_', name)

def load_config(config_path: str = "config.json") -> dict:
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)
# ---------------------------------------------

def main():
    try:
        config = load_config()
    except FileNotFoundError:
        print("❌ Файл config.json не найден.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка в config.json: {e}")
        sys.exit(1)

    tableau_cfg = config.get("tableau", {})
    server = tableau_cfg.get("server")
    api_version = tableau_cfg.get("api_version")
    site = tableau_cfg.get("site", "")
    verify_ssl = tableau_cfg.get("verify_ssl", True)
    auth_cfg = tableau_cfg.get("auth", {})
    auth_type = auth_cfg.get("type", "password")
    username = auth_cfg.get("username", "")
    password = auth_cfg.get("password", "")

    project_id = config.get("project_id")          # может быть число или строка
    project_luid = config.get("project_luid")
    project_name = config.get("project_name")
    download_path = config.get("download_path")

    if not server or not api_version or not download_path:
        print("❌ Не хватает обязательных полей: server, api_version, download_path")
        sys.exit(1)

    # Определяем, что передано
    if not project_id and not project_luid and not project_name:
        print("❌ Укажите один из: project_id (числовой), project_luid (UUID), project_name (строка)")
        sys.exit(1)

    # Если передан project_id, конвертируем в int (если строка)
    if project_id is not None:
        try:
            project_id = int(project_id)
        except ValueError:
            print(f"❌ project_id должен быть числом, получено: {project_id}")
            sys.exit(1)

    if auth_type == "password" and not password:
        username = input("👤 Введите имя пользователя: ") if not username else username
        password = getpass.getpass("🔑 Введите пароль: ")

    client = TableauClient(server, api_version, site, verify_ssl)
    try:
        token, site_id = client.sign_in(username, password)
        print(f"✅ Аутентификация успешна. Site ID: {site_id}")
    except Exception as e:
        print(f"❌ Ошибка аутентификации: {e}")
        sys.exit(1)

    # Получаем LUID проекта
    target_luid = None
    if project_luid:
        target_luid = project_luid
        print(f"📌 Используем LUID проекта: {target_luid}")
    elif project_name:
        print(f"🔍 Ищем проект по имени: {project_name}")
        target_luid = client.get_project_luid_by_name(project_name)
        if not target_luid:
            print(f"❌ Проект с именем '{project_name}' не найден.")
            client.sign_out()
            sys.exit(1)
        print(f"   Найден LUID: {target_luid}")
    elif project_id is not None:
        print(f"🔍 Ищем проект по числовому ID: {project_id}")
        target_luid = client.get_project_luid_by_numeric_id(project_id)
        if not target_luid:
            print(f"❌ Проект с числовым ID {project_id} не найден.")
            # Выведем список проектов для отладки
            print("📋 Список проектов на сайте:")
            url = f"{server}/api/{api_version}/sites/{site_id}/projects"
            headers = {"X-Tableau-Auth": token, "Accept": "application/xml"}
            resp = requests.get(url, headers=headers, verify=verify_ssl)
            root = ET.fromstring(resp.content)
            ns = {'t': 'http://tableau.com/api'}
            for proj in root.findall('.//t:project', ns):
                print(f"   {proj.get('name')} (LUID: {proj.get('id')}) - webpageUrl: {proj.get('webpageUrl', '')}")
            client.sign_out()
            sys.exit(1)
        print(f"   Найден LUID: {target_luid}")

    # Теперь скачиваем книги из проекта с target_luid
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
            if project_el is not None:
                wb_project_luid = project_el.get('id')
            else:
                wb_project_luid = None
            if wb_id and wb_name and wb_project_luid == target_luid:
                all_workbooks.append((wb_id, wb_name))

        if len(root.findall('.//t:workbook', ns)) < page_size:
            break
        page += 1

    if not all_workbooks:
        print(f"ℹ️ В проекте с LUID {target_luid} не найдено книг.")
        client.sign_out()
        sys.exit(0)

    print(f"📚 Найдено книг: {len(all_workbooks)}")
    os.makedirs(download_path, exist_ok=True)

    for wb_id, wb_name in all_workbooks:
        print(f"⬇️ Скачивание: {wb_name} (ID: {wb_id})")
        download_url = f"{server}/api/{api_version}/sites/{client.site_id}/workbooks/{wb_id}/content"
        try:
            resp = requests.get(download_url, headers={"X-Tableau-Auth": client.token}, stream=True, verify=verify_ssl)
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