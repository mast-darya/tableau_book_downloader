# Tableau Book Downloader

Скрипт для скачивания всех книг (workbooks) из указанного проекта Tableau Server с использованием REST API (XML).
Книги с экстрактами скачиваются как .twbx, без экстрактов – как .twb

## 📦 Требования
- Python 3.7+
- Библиотека `requests`

## ⚙️ Установка
```bash
git clone https://github.com/mast-darya/tableau_book_downloader.git
cd tableau_book_downloader
pip install requests
```
## ⚙️ Использование
```bash
python test.py
```
В поле project_id (ПОКА) нужно передавать luid объекта. 
Ищется по таблице project через числовой id из url 