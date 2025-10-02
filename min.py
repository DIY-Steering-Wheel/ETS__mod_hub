import os
import json
import threading
import gdown
import zipfile
import requests
import shutil
import tkinter as tk
from tkinter import messagebox, ttk
import time

# DETECTA DOCUMENTS E ETS2
DOCUMENTS_FOLDER = os.path.join(os.path.expanduser("~"), "Documents")
EUROTRUCK_PATH = os.path.join(DOCUMENTS_FOLDER, "Euro Truck Simulator 2")
MODS_FOLDER = os.path.join(EUROTRUCK_PATH, "mod")
PROFILES_FOLDER = os.path.join(EUROTRUCK_PATH, "profiles")

# NOVO LINK
JSON_URL = "https://raw.githubusercontent.com/DIY-Steering-Wheel/ETS__mod_hub/refs/heads/main/mods.json"

DOWNLOADING = False
cancel_flag = False
mods_list = []


def download_and_install(mod, status_text, modal, progress_bar, cancel_btn):
    global DOWNLOADING, cancel_flag
    if DOWNLOADING:
        messagebox.showinfo("Atenção", "Já existe um download em andamento!")
        return

    DOWNLOADING = True
    cancel_flag = False
    temp_zip = os.path.join(os.getcwd(), "temp_mod.zip")

    try:
        status_text.set(f"Baixando {mod['name']}...")
        root.update_idletasks()

        # Download com timeout de aviso
        start_time = time.time()
        try:
            gdown.download(mod['drive_link'], temp_zip, quiet=False)
        except Exception:
            status_text.set("Erro de Internet")
            messagebox.showerror("Erro de Internet", "Não foi possível acessar o arquivo na web.")
            modal.destroy()
            return

        if time.time() - start_time > 10:
            status_text.set("Algumas instalações podem demorar vários minutos.\nEspere. Caso houver erros, informaremos a você.")

        if cancel_flag:
            status_text.set("Operação cancelada")
            modal.destroy()
            return

        # Esconde botão de cancelar
        cancel_btn.pack_forget()

        # Extração com barra de progresso
        status_text.set("Extraindo arquivos...")
        root.update_idletasks()
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            file_list = zip_ref.namelist()
            total_files = len(file_list)
            for i, file in enumerate(file_list, start=1):
                zip_ref.extract(file, "temp_mod")
                progress_bar["value"] = (i / total_files) * 100
                root.update_idletasks()

        temp_mod_path = "temp_mod"

        # Instalar mods
        mods_path = os.path.join(temp_mod_path, "mods")
        if os.path.exists(mods_path):
            for item in os.listdir(mods_path):
                s = os.path.join(mods_path, item)
                d = os.path.join(MODS_FOLDER, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)

        # Instalar perfis
        perfil_path = os.path.join(temp_mod_path, "perfil")
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
        if os.path.exists(temp_zip):
            os.remove(temp_zip)
        if os.path.exists("temp_mod"):
            shutil.rmtree("temp_mod", ignore_errors=True)
        DOWNLOADING = False
        cancel_flag = False
        modal.destroy()


# ABRIR MODAL
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
    modal.iconbitmap(os.path.abspath("icon.ico"))


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
        modal.destroy()

    cancel_btn = tk.Button(modal, text="Cancelar", command=cancel_operation)
    cancel_btn.pack(pady=10)

    # Thread do processo
    threading.Thread(
        target=download_and_install,
        args=(mod, status_text, modal, progress_bar, cancel_btn),
        daemon=True
    ).start()


# CARREGA MODS COM TRATAMENTO DE ERRO
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


# ATUALIZA TREEVIEW COM FILTRO DE PESQUISA
def update_treeview(*args):
    search = search_var.get().lower()
    for i in tree.get_children():
        tree.delete(i)
    for idx, mod in enumerate(mods_list):
        if search in mod['name'].lower() or search in mod.get('description', '').lower():
            tree.insert("", "end", iid=idx, values=(mod['name'], mod.get('description', '')))


# GUI
root = tk.Tk()
root.title("Instalador de Expansões ETS2 By valdemir")
root.geometry("700x500")
root.iconbitmap(os.path.abspath("icon.ico"))

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
