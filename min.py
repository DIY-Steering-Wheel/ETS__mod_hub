import os
import json
import threading
import zipfile
import requests
import shutil
import tkinter as tk
from tkinter import messagebox, ttk
import time
import tempfile
import math

# Tente importar gdown (se não existir, seguiremos com fallback)
try:
    import gdown
    HAVE_GDOWN = True
except Exception:
    HAVE_GDOWN = False

# DETECTA DOCUMENTS E ETS2
DOCUMENTS_FOLDER = os.path.join(os.path.expanduser("~"), "Documents")
EUROTRUCK_PATH = os.path.join(DOCUMENTS_FOLDER, "Euro Truck Simulator 2")
MODS_FOLDER = os.path.join(EUROTRUCK_PATH, "mod")
PROFILES_FOLDER = os.path.join(EUROTRUCK_PATH, "profiles")

# Garanta que pastas existam
os.makedirs(MODS_FOLDER, exist_ok=True)
os.makedirs(PROFILES_FOLDER, exist_ok=True)

# NOVO LINK
JSON_URL = "https://raw.githubusercontent.com/DIY-Steering-Wheel/ETS__mod_hub/refs/heads/main/mods.json"

DOWNLOADING = False
cancel_flag = False
mods_list = []

# --- util: detectar link google drive (simples) ---
def is_google_drive_link(url: str) -> bool:
    return "drive.google.com" in url or "drive.googleusercontent.com" in url

# --- util: download via requests streaming com progress ---
def download_with_requests(url, out_path, progress_callback=None, timeout=15):
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0"}
    with session.get(url, stream=True, timeout=timeout, headers=headers) as r:
        r.raise_for_status()
        total = r.headers.get("content-length")
        if total is None:
            # sem content-length: gravar sem barra percentual confiável
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if cancel_flag:
                        return False
                    if chunk:
                        f.write(chunk)
                        if progress_callback:
                            progress_callback(None)  # sem total
            return True
        else:
            total = int(total)
            written = 0
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if cancel_flag:
                        return False
                    if chunk:
                        f.write(chunk)
                        written += len(chunk)
                        if progress_callback:
                            progress_callback(written, total)
            return True

# --- util: tenta baixar com gdown ou requests com retries ---
def robust_download(url, out_path, progress_callback=None, status_text=None, retries=3):
    last_exception = None
    for attempt in range(1, retries + 1):
        try:
            if status_text:
                status_text.set(f"Tentativa {attempt} de {retries}...")
                root.update_idletasks()

            if is_google_drive_link(url) and HAVE_GDOWN:
                # gdown retorna True/arquivo; usar quiet=True para não poluir
                # gdown trata confirm prompts para arquivos grandes
                try:
                    gdown.download(url, out_path, quiet=True)
                    # verifique se arquivo foi realmente criado
                    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                        if progress_callback:
                            # não temos total, marque 100%
                            progress_callback(1, 1)
                        return True
                    else:
                        raise RuntimeError("gdown baixou arquivo vazio.")
                except Exception as e:
                    last_exception = e
                    # fallback para requests se gdown falhar
                    if status_text:
                        status_text.set("gdown falhou, tentando fallback com requests...")
                    # continue para bloco requests abaixo
            # fallback / link comum: requests streaming
            success = download_with_requests(url, out_path, progress_callback=progress_callback)
            if success:
                return True
        except Exception as e:
            last_exception = e
            if status_text:
                status_text.set(f"Erro: {e}. Retentando...")
            time.sleep(1 + attempt)  # backoff simples
    # todas as tentativas falharam
    raise last_exception if last_exception is not None else RuntimeError("Falha desconhecida no download.")

# --- função principal de download e instalação ---
def download_and_install(mod, status_text, modal, progress_bar, cancel_btn):
    global DOWNLOADING, cancel_flag
    if DOWNLOADING:
        messagebox.showinfo("Atenção", "Já existe um download em andamento!")
        return

    DOWNLOADING = True
    cancel_flag = False

    tmp_dir = tempfile.mkdtemp(prefix="ets2_mod_")
    temp_zip = os.path.join(tmp_dir, "temp_mod.zip")

    try:
        status_text.set(f"Baixando {mod['name']}...")
        root.update_idletasks()

        start_time = time.time()

        # função de callback que atualiza a progressbar a partir de bytes
        def progress_cb(written, total):
            if cancel_flag:
                return
            if total and total > 0:
                percent = (written / total) * 100
                progress_bar["value"] = percent
            else:
                # sem total conhecido: anima a barra incrementalmente
                progress_bar.step(5)
            root.update_idletasks()

        try:
            robust_download(mod['drive_link'], temp_zip, progress_callback=progress_cb, status_text=status_text, retries=3)
        except Exception as e:
            status_text.set("Erro ao baixar arquivo")
            messagebox.showerror("Erro de Download", f"Não foi possível baixar {mod['name']}.\nDetalhe: {e}")
            return

        elapsed = time.time() - start_time
        if elapsed > 10:
            status_text.set("Algumas instalações podem demorar vários minutos.\nEspere. Caso houver erros, informaremos a você.")
            root.update_idletasks()

        if cancel_flag:
            status_text.set("Operação cancelada")
            return

        # Esconde botão de cancelar (opcional)
        try:
            cancel_btn.pack_forget()
        except Exception:
            pass

        # Extração com barra de progresso
        status_text.set("Extraindo arquivos...")
        root.update_idletasks()
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            file_list = zip_ref.namelist()
            total_files = len(file_list) if file_list else 0
            for i, file in enumerate(file_list, start=1):
                if cancel_flag:
                    status_text.set("Cancelando extração...")
                    return
                zip_ref.extract(file, tmp_dir)
                if total_files > 0:
                    progress_bar["value"] = (i / total_files) * 100
                else:
                    progress_bar.step(5)
                root.update_idletasks()

        temp_mod_path = os.path.join(tmp_dir, "")

        # Instalar mods (procura pasta 'mods' dentro do zip)
        mods_path = os.path.join(tmp_dir, "mods")
        if os.path.exists(mods_path):
            for item in os.listdir(mods_path):
                s = os.path.join(mods_path, item)
                d = os.path.join(MODS_FOLDER, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)

        # Instalar perfis
        perfil_path = os.path.join(tmp_dir, "perfil")
        if os.path.exists(perfil_path):
            for item in os.listdir(perfil_path):
                s = os.path.join(perfil_path, item)
                d = os.path.join(PROFILES_FOLDER, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)

        status_text.set("Instalação concluída!")
        messagebox.showinfo("Concluído", f"{mod['name']} instalado com sucesso!")

    except Exception as e:
        status_text.set("Ocorreu um erro")
        messagebox.showerror("Erro", f"Ocorreu um erro: {e}")
    finally:
        # cleanup
        try:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
        except Exception:
            pass
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
        DOWNLOADING = False
        cancel_flag = False
        try:
            modal.destroy()
        except Exception:
            pass

# --- ABRIR MODAL ---
def start_download_modal():
    selected = tree.selection()
    if not selected:
        messagebox.showinfo("Seleção", "Escolha uma expansão para instalar.")
        return
    mod_index = int(selected[0])
    mod = mods_list[mod_index]

    # Janela modal
    modal = tk.Toplevel(root)
    modal.title(f"Instalando {mod['name']}")
    modal.transient(root)
    modal.grab_set()
    modal.geometry("400x220")
    modal.resizable(False, False)
    # Se tiver icon.ico empacotado, pode funcionar; tratamos exceções
    try:
        modal.iconbitmap(os.path.abspath("icon.ico"))
    except Exception:
        pass

    status_text = tk.StringVar()
    status_text.set("Iniciando...")

    label = tk.Label(modal, textvariable=status_text, font=("Arial", 12))
    label.pack(pady=10)

    # Barra de progresso da extração
    progress_bar = ttk.Progressbar(modal, orient="horizontal", length=300, mode="determinate")
    progress_bar.pack(pady=10)

    # Botão Cancelar (só no download)
    def cancel_operation():
        global cancel_flag
        cancel_flag = True
        status_text.set("Cancelando...")
        # não destruir modal imediatamente para mostrar progresso
        # modal.destroy()

    cancel_btn = tk.Button(modal, text="Cancelar", command=cancel_operation)
    cancel_btn.pack(pady=10)

    # Thread do processo
    threading.Thread(
        target=download_and_install,
        args=(mod, status_text, modal, progress_bar, cancel_btn),
        daemon=True
    ).start()

# --- CARREGA MODS COM TRATAMENTO DE ERRO ---
def load_mods():
    global mods_list
    try:
        response = requests.get(JSON_URL, timeout=10)
        response.raise_for_status()
        mods_list = response.json()
    except requests.RequestException:
        messagebox.showwarning("Aviso", "Não foi possível acessar a lista de expansões. Verifique sua internet.")
        mods_list = []
    except json.JSONDecodeError:
        messagebox.showwarning("Aviso", "Erro ao interpretar a lista de expansões.")
        mods_list = []

    update_treeview()

# --- ATUALIZA TREEVIEW COM FILTRO DE PESQUISA ---
def update_treeview(*args):
    search = search_var.get().lower()
    for i in tree.get_children():
        tree.delete(i)
    for idx, mod in enumerate(mods_list):
        if search in mod['name'].lower() or search in mod.get('description', '').lower():
            tree.insert("", "end", iid=idx, values=(mod['name'], mod.get('description', '')))

# --- GUI ---
root = tk.Tk()
root.title("Instalador de Expansões ETS2 By valdemir")
root.geometry("700x500")
try:
    root.iconbitmap(os.path.abspath("icon.ico"))
except Exception:
    pass

main_frame = tk.Frame(root)
main_frame.pack(fill="both", expand=True, padx=10, pady=10)

# Barra de pesquisa
search_frame = tk.Frame(main_frame)
search_frame.pack(fill="x", pady=5)

tk.Label(search_frame, text="Pesquisar:").pack(side="left")
search_var = tk.StringVar()
search_var.trace_add("write", update_treeview)
search_entry = tk.Entry(search_frame, textvariable=search_var)
search_entry.pack(side="left", fill="x", expand=True, padx=5)

# Lista de expansões
list_frame = tk.LabelFrame(main_frame, text="Lista de Expansões Disponíveis")
list_frame.pack(fill="both", expand=True, pady=5)

columns = ("Nome", "Descrição")
tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=18)
tree.heading("Nome", text="Nome")
tree.heading("Descrição", text="Descrição")
tree.column("Nome", width=200)
tree.column("Descrição", width=450)
tree.pack(side="left", fill="both", expand=True)

scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
tree.configure(yscroll=scrollbar.set)
scrollbar.pack(side="right", fill="y")

# Botões
button_frame = tk.Frame(main_frame)
button_frame.pack(fill="x", pady=5)

install_btn = tk.Button(button_frame, text="Instalar Expansão Selecionada", command=start_download_modal)
install_btn.pack(side="left", padx=5)

refresh_btn = tk.Button(button_frame, text="Atualizar Lista", command=load_mods)
refresh_btn.pack(side="left", padx=5)

# Inicializa lista
load_mods()
root.mainloop()
