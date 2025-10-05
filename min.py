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
import ctypes
import sys

# Tente importar gdown (se não existir, seguiremos com fallback)
try:
    import gdown
    HAVE_GDOWN = True
except Exception:
    HAVE_GDOWN = False

# --- Função: detecção robusta da pasta Documents (Windows/Unix) ---
def get_documents_folder():
    """
    Tenta obter a pasta 'Documents' de forma robusta:
    1) usa Known Folders no Windows (se disponível)
    2) tenta ~/Documents e ~/Documentos
    3) fallback para ~/Documents
    """
    # Windows Known Folder (FOLDERID_Documents)
    if sys.platform.startswith("win"):
        try:
            _SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
            _SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
            _SHGetKnownFolderPath.restype = ctypes.c_long
            # GUID for Documents as bytes
            FOLDERID_Documents = ctypes.c_wchar_p("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")
            ptr = ctypes.c_wchar_p()
            res = _SHGetKnownFolderPath(ctypes.byref(ctypes.create_unicode_buffer("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")), 0, 0, ctypes.byref(ptr))
            # se falhar, vamos pros próximos
            if res == 0 and ptr.value:
                return ptr.value
        except Exception:
            pass

    # try common names
    home = os.path.expanduser("~")
    for candidate in ("Documents", "Documentos", "Meus Documentos"):
        path = os.path.join(home, candidate)
        if os.path.isdir(path):
            return path

    # fallback
    return os.path.join(home, "Documents")

# DETECTA DOCUMENTS E ETS2
DOCUMENTS_FOLDER = get_documents_folder()
EUROTRUCK_PATH = os.path.join(DOCUMENTS_FOLDER, "Euro Truck Simulator 2")
MODS_FOLDER = os.path.join(EUROTRUCK_PATH, "mod")
PROFILES_FOLDER = os.path.join(EUROTRUCK_PATH, "profiles")

# Garanta que pastas existam
os.makedirs(MODS_FOLDER, exist_ok=True)
os.makedirs(PROFILES_FOLDER, exist_ok=True)

# NOVO LINK (exemplo: substitua se quiser)
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
                try:
                    # gdown lida com confirm prompts para arquivos grandes
                    gdown.download(url, out_path, quiet=True)
                    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                        if progress_callback:
                            progress_callback(1, 1)
                        return True
                    else:
                        raise RuntimeError("gdown baixou arquivo vazio.")
                except Exception as e:
                    last_exception = e
                    if status_text:
                        status_text.set("gdown falhou, tentando fallback com requests...")
                    # cair para requests
            # fallback: requests
            success = download_with_requests(url, out_path, progress_callback=progress_callback)
            if success:
                return True
        except Exception as e:
            last_exception = e
            if status_text:
                status_text.set(f"Erro: {e}. Retentando...")
            time.sleep(1 + attempt)
    raise last_exception if last_exception is not None else RuntimeError("Falha desconhecida no download.")

# --- util: copia tudo que estiver dentro de pastas 'mods'/'mod' e 'perfil'/'profile' encontradas ---
def copy_all_from_named_folders(extracted_root):
    """
    Varre extracted_root procurando por pastas com nomes:
    - mods, mod  -> copia TODO o conteúdo dessas pastas (arquivos e subpastas) para MODS_FOLDER
    - perfil, profile, profiles -> copia TODO o conteúdo dessas pastas (ou a pasta inteira) para PROFILES_FOLDER

    Retorna um dicionário com o que foi copiado para exibição.
    """
    copied = {"mods_files": [], "mods_folders": [], "profiles": []}

    # procura recursivamente por qualquer pasta cujo nome seja igual a uma das chaves
    for root_dir, dirs, files in os.walk(extracted_root):
        # verificar cada subpasta
        for d in list(dirs):  # list() para evitar alteração enquanto itera
            lower = d.lower()
            full_d_path = os.path.join(root_dir, d)
            try:
                if lower in ("mods", "mod"):
                    # copiar tudo que está DENTRO desta pasta para MODS_FOLDER
                    for item in os.listdir(full_d_path):
                        src = os.path.join(full_d_path, item)
                        dest = os.path.join(MODS_FOLDER, item)
                        if os.path.isdir(src):
                            # copia pasta inteira (mergear caso exista)
                            shutil.copytree(src, dest, dirs_exist_ok=True)
                            copied["mods_folders"].append(dest)
                        else:
                            # arquivo simples
                            shutil.copy2(src, dest)
                            copied["mods_files"].append(dest)
                elif lower in ("perfil", "profile", "profiles"):
                    # copiar TUDO DENTRO dessa pasta para a pasta de profiles
                    # se a pasta dentro do zip já tiver o nome do profile, vamos criar pasta com esse nome dentro de PROFILES_FOLDER
                    for item in os.listdir(full_d_path):
                        src = os.path.join(full_d_path, item)
                        dest = os.path.join(PROFILES_FOLDER, item)
                        if os.path.isdir(src):
                            shutil.copytree(src, dest, dirs_exist_ok=True)
                            copied["profiles"].append(dest)
                        else:
                            # arquivo solto dentro da pasta profile -> colocamos dentro de uma pasta chamada pelo nome da pasta d
                            container_dir = os.path.join(PROFILES_FOLDER, d)
                            os.makedirs(container_dir, exist_ok=True)
                            dest_file = os.path.join(container_dir, item)
                            shutil.copy2(src, dest_file)
                            copied["profiles"].append(dest_file)
            except Exception as e:
                # continuar a busca mesmo que algum copy falhe
                print("Erro ao copiar", full_d_path, e)

    return copied

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
                try:
                    progress_bar.step(5)
                except Exception:
                    pass
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
                # evita caminhos com traversal
                safe_name = os.path.normpath(file)
                if safe_name.startswith(".."):
                    continue
                zip_ref.extract(file, tmp_dir)
                if total_files > 0:
                    progress_bar["value"] = (i / total_files) * 100
                else:
                    try:
                        progress_bar.step(5)
                    except Exception:
                        pass
                root.update_idletasks()

        if cancel_flag:
            status_text.set("Operação cancelada")
            return

        # --- NOVO: copiar TUDO que estiver dentro de pastas chamadas mods/mod/perfil/profile/profiles ---
        status_text.set("Instalando arquivos (copiando pastas 'mods'/'perfil')...")
        root.update_idletasks()

        copied_info = copy_all_from_named_folders(tmp_dir)

        # Se nada foi copiado, avisar (mas NÃO tentar heurísticas extras — você pediu para copiar apenas o conteúdo de pastas nomeadas)
        if not copied_info["mods_files"] and not copied_info["mods_folders"] and not copied_info["profiles"]:
            status_text.set("Nenhuma pasta 'mods' ou 'perfil' encontrada no pacote. Nada copiado.")
            root.update_idletasks()
            messagebox.showwarning("Aviso", "Não foi encontrada nenhuma pasta chamada 'mods' ou 'perfil' dentro do pacote. Nada foi copiado automaticamente.")
        else:
            # sumário para o usuário
            summary_lines = []
            if copied_info["mods_files"]:
                summary_lines.append("Arquivos copiados para mod/:")
                for p in copied_info["mods_files"]:
                    summary_lines.append("  - " + p)
            if copied_info["mods_folders"]:
                summary_lines.append("Pastas copiadas para mod/:")
                for p in copied_info["mods_folders"]:
                    summary_lines.append("  - " + p)
            if copied_info["profiles"]:
                summary_lines.append("Itens copiados para profiles/:")
                for p in copied_info["profiles"]:
                    summary_lines.append("  - " + p)

            status_text.set("Instalação concluída!")
            root.update_idletasks()
            messagebox.showinfo("Concluído - Itens copiados", "\n".join(summary_lines))

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
