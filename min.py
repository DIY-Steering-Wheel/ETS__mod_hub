# ETS2 Mod Installer - Atualizado:
# - Notifica se não encontrou pasta mods ou se ela estava vazia (0 mods encontrados)
# - Botão "Baixar RAW" (baixa o ZIP para Downloads sem instalar; exige confirmação do usuário)
# - Mantém: gdown-only, fila (Baixar Fila), logs, aba "Instalados", comportamento de mods/perfis pedidos anteriormente
# Requer: pip install gdown

import os
import json
import threading
import zipfile
import shutil
import tkinter as tk
from tkinter import messagebox, ttk
import time
import tempfile
import ctypes
import sys
from datetime import datetime

# tentar importar gdown (obrigatório para downloads)
try:
    import gdown
    HAVE_GDOWN = True
except Exception:
    HAVE_GDOWN = False

# ---------- Configs e pastas ----------
def get_documents_folder():
    if sys.platform.startswith("win"):
        try:
            _SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
            _SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
            _SHGetKnownFolderPath.restype = ctypes.c_long
            buf = ctypes.c_wchar_p()
            guid = ctypes.create_unicode_buffer("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")
            res = _SHGetKnownFolderPath(ctypes.byref(guid), 0, 0, ctypes.byref(buf))
            if res == 0 and buf.value:
                return buf.value
        except Exception:
            pass
    home = os.path.expanduser("~")
    for candidate in ("Documents", "Documentos", "Meus Documentos"):
        path = os.path.join(home, candidate)
        if os.path.isdir(path):
            return path
    return os.path.join(home, "Documents")

DOCUMENTS_FOLDER = get_documents_folder()
EUROTRUCK_PATH = os.path.join(DOCUMENTS_FOLDER, "Euro Truck Simulator 2")
MODS_FOLDER = os.path.join(EUROTRUCK_PATH, "mod")
PROFILES_FOLDER = os.path.join(EUROTRUCK_PATH, "profiles")
os.makedirs(MODS_FOLDER, exist_ok=True)
os.makedirs(PROFILES_FOLDER, exist_ok=True)

# Downloads folder (para "Baixar RAW")
def get_downloads_folder():
    home = os.path.expanduser("~")
    # Windows generally has "Downloads", mac/linux usually also
    for candidate in ("Downloads", "Download"):
        d = os.path.join(home, candidate)
        if os.path.isdir(d):
            return d
    # fallback para home
    return home

DOWNLOADS_FOLDER = get_downloads_folder()

LOG_FOLDER = os.path.join(DOCUMENTS_FOLDER, "ets2_installer_logs")
os.makedirs(LOG_FOLDER, exist_ok=True)
LOG_FILE = os.path.join(LOG_FOLDER, datetime.now().strftime("log_%Y%m%d_%H%M%S.txt"))

def write_log(line: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] {line}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception:
        pass

JSON_URL = "https://raw.githubusercontent.com/DIY-Steering-Wheel/ETS__mod_hub/refs/heads/main/mods.json"

DOWNLOADING = False
cancel_flag = False
mods_list = []

# fila
install_queue = []
queue_running = False
queue_stop_requested = False

# ---------- util gdown ----------
def require_gdown_or_fail():
    if not HAVE_GDOWN:
        msg = ("O 'gdown' não está instalado neste sistema. Instale com:\n\npip install gdown\n\n"
               "Este instalador foi configurado para usar SOMENTE gdown para downloads.")
        write_log("gdown ausente: downloads bloqueados.")
        try:
            messagebox.showerror("gdown ausente", msg)
        except Exception:
            pass
        raise RuntimeError("gdown não instalado")

def robust_download_with_gdown(url, out_path):
    require_gdown_or_fail()
    try:
        result = gdown.download(url, out_path, quiet=True, fuzzy=True)
        if result is None and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            return True
        if result is not None and os.path.exists(result) and os.path.getsize(result) > 0:
            if os.path.abspath(result) != os.path.abspath(out_path):
                try:
                    shutil.move(result, out_path)
                except Exception:
                    write_log(f"gdown salvou em {result}, não foi possível mover para {out_path}.")
            return True
        raise RuntimeError("gdown não retornou arquivo válido (arquivo ausente ou vazio).")
    except Exception as e:
        write_log(f"robust_download_with_gdown falhou para URL {url}: {e}")
        raise

# ---------- detectar/operar sobre mods/profiles ----------
def detect_named_folders(extracted_root):
    mods_dirs = []
    profiles_dirs = []
    for root_dir, dirs, files in os.walk(extracted_root):
        for d in dirs:
            lower = d.lower()
            full = os.path.join(root_dir, d)
            if lower in ("mods", "mod"):
                if full not in mods_dirs:
                    mods_dirs.append(full)
            if lower in ("perfil", "profile", "profiles"):
                if full not in profiles_dirs:
                    profiles_dirs.append(full)
    return {"mods_dirs": mods_dirs, "profiles_dirs": profiles_dirs}

def copy_mods_from_dirs(mods_dirs):
    copied = {"mods_files": [], "mods_folders": []}
    total_items = 0
    for mods_root in mods_dirs:
        try:
            items = os.listdir(mods_root)
        except Exception:
            items = []
        total_items += len(items)
        for item in items:
            src = os.path.join(mods_root, item)
            dest = os.path.join(MODS_FOLDER, item)
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                    copied["mods_folders"].append(dest)
                    write_log(f"Copiado diretório de mod: {dest}")
                else:
                    shutil.copy2(src, dest)
                    copied["mods_files"].append(dest)
                    write_log(f"Copiado arquivo de mod: {dest}")
            except Exception as e:
                write_log(f"ERRO ao copiar mod {src} -> {dest}: {e}")
    copied["total_items"] = total_items
    return copied

def prepare_profiles_copy_list(profiles_dirs):
    to_copy = []
    for p_root in profiles_dirs:
        for item in os.listdir(p_root):
            src = os.path.join(p_root, item)
            dest = os.path.join(PROFILES_FOLDER, item)
            is_dir = os.path.isdir(src)
            exists = os.path.exists(dest)
            to_copy.append({"src": src, "dest": dest, "is_dir": is_dir, "exists": exists, "container_name": os.path.basename(p_root)})
    return to_copy

def copy_profiles_with_decision(to_copy, overwrite=False):
    copied = []
    skipped = []
    errors = []
    for item in to_copy:
        src = item["src"]
        dest = item["dest"]
        try:
            if item["is_dir"]:
                if os.path.exists(dest):
                    if overwrite:
                        # backup optional (not implemented) - here we simply remove then copy
                        try:
                            shutil.rmtree(dest)
                        except Exception:
                            pass
                        shutil.copytree(src, dest, dirs_exist_ok=True)
                        copied.append(dest)
                        write_log(f"Substituído profile (diretório): {dest}")
                    else:
                        skipped.append(dest)
                        write_log(f"Ignorado profile (já existe): {dest}")
                else:
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                    copied.append(dest)
                    write_log(f"Copiado profile (diretório): {dest}")
            else:
                if os.path.exists(dest):
                    if overwrite:
                        shutil.copy2(src, dest)
                        copied.append(dest)
                        write_log(f"Substituído arquivo de profile: {dest}")
                    else:
                        skipped.append(dest)
                        write_log(f"Ignorado arquivo de profile (já existe): {dest}")
                else:
                    shutil.copy2(src, dest)
                    copied.append(dest)
                    write_log(f"Copiado arquivo de profile: {dest}")
        except Exception as e:
            errors.append({"src": src, "dest": dest, "error": str(e)})
            write_log(f"ERRO ao copiar profile {src} -> {dest}: {e}")
    return {"copied": copied, "skipped": skipped, "errors": errors}

def ask_overwrite_profiles(conflicting_names):
    text = "Foram encontrados perfis com os mesmos nomes já instalados:\n\n"
    text += "\n".join(conflicting_names[:20])
    if len(conflicting_names) > 20:
        text += f"\n... (+{len(conflicting_names)-20} outros)\n"
    text += "\n\nDeseja substituir os perfis existentes? (Sim = substituir, Não = preservar existentes)"
    return messagebox.askyesno("Conflito de Profiles", text)

# ---------- download + instalação (thread) ----------
def download_and_install(mod, status_text, modal, progress_bar, cancel_btn, on_complete=None):
    global DOWNLOADING, cancel_flag
    if DOWNLOADING:
        if on_complete:
            try: root.after(0, lambda: on_complete(False, "Já existe um download em andamento", {}))
            except: pass
        return

    DOWNLOADING = True
    cancel_flag = False
    tmp_dir = tempfile.mkdtemp(prefix="ets2_mod_")
    temp_zip = os.path.join(tmp_dir, "temp_mod_download")
    success = False
    info = ""
    details = {}

    try:
        status_text.set(f"Baixando {mod['name']} (gdown)...")
        try: root.update_idletasks()
        except: pass

        # animar
        try:
            progress_bar.config(mode='indeterminate')
            progress_bar.start(12)
        except:
            pass

        try:
            robust_download_with_gdown(mod['drive_link'], temp_zip)
        except Exception as e:
            status_text.set("Erro ao baixar arquivo (gdown)")
            write_log(f"{mod['name']}: ERRO ao baixar com gdown: {e}")
            details = {"error": str(e)}
            success = False
            return

        try:
            progress_bar.stop()
            progress_bar.config(mode='determinate')
            progress_bar["value"] = 0
        except:
            pass

        if cancel_flag:
            status_text.set("Operação cancelada")
            write_log(f"{mod['name']}: CANCELADO (após download)")
            details = {"cancelled": True}
            success = False
            return

        status_text.set("Extraindo...")
        try: root.update_idletasks()
        except: pass

        extracted = False
        try:
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(tmp_dir)
                extracted = True
        except zipfile.BadZipFile:
            write_log(f"{mod['name']}: Arquivo não é zip. Tentando salvar como arquivo único em mod/")
            try:
                with open(temp_zip, "rb") as f:
                    head = f.read(4096)
                head_text = head.decode('utf-8', errors='ignore').strip().lower()
            except Exception:
                head_text = ""
            if head_text.startswith("<!doctype") or head_text.startswith("<html") or "drive.google.com" in head_text:
                saved = os.path.join(LOG_FOLDER, f"{mod['name']}_raw.html")
                try:
                    shutil.copy2(temp_zip, saved)
                    write_log(f"{mod['name']}: Conteúdo HTML salvo em {saved}")
                except Exception:
                    pass
                messagebox.showerror("Erro", f"O arquivo baixado para '{mod['name']}' parece ser uma página HTML (erro/permissão). Verifique o link no Drive.")
                details = {"html_saved": saved}
                success = False
                return
            else:
                guessed = (mod.get("filename") or mod['name'].replace(" ", "_")) + ".scs"
                dest = os.path.join(MODS_FOLDER, guessed)
                if os.path.exists(dest):
                    base, ext = os.path.splitext(guessed)
                    i = 1
                    while True:
                        cand = f"{base}_{i}{ext}"
                        if not os.path.exists(os.path.join(MODS_FOLDER, cand)):
                            dest = os.path.join(MODS_FOLDER, cand)
                            break
                        i += 1
                try:
                    shutil.copy2(temp_zip, dest)
                    write_log(f"{mod['name']}: Arquivo não-zip salvo em mod/: {dest}")
                    status_text.set("Arquivo não-zip salvo em mod/")
                    details = {"saved_as": dest}
                    success = True
                    return
                except Exception as e:
                    write_log(f"{mod['name']}: Falha ao salvar não-zip: {e}")
                    details = {"error_save": str(e)}
                    success = False
                    return

        # se extraído, detectar estrutura
        structure = detect_named_folders(tmp_dir)
        mods_dirs = structure["mods_dirs"]
        profiles_dirs = structure["profiles_dirs"]

        # Se não encontrou nenhuma pasta 'mods', avisar e marcar 0 mods encontrados (mensagem + log)
        mods_detected_count = 0
        copied_mods_info = {}
        if not mods_dirs:
            write_log(f"{mod['name']}: Nenhuma pasta 'mods' encontrada no pacote.")
            # vamos definir explicitamente 0 mods encontrados no resumo
            mods_detected_count = 0
        else:
            # contar itens dentro das pastas mods para saber se está vazia
            copied_mods_info = copy_mods_from_dirs(mods_dirs)
            mods_detected_count = copied_mods_info.get("total_items", 0)
            if mods_detected_count == 0:
                # pasta 'mods' encontrada mas vazia
                write_log(f"{mod['name']}: Pasta 'mods' encontrada mas vazia.")
                # user notification
                try:
                    messagebox.showinfo("Mods vazios", f"O pacote '{mod['name']}' contém uma pasta 'mods', mas ela está vazia (0 mods encontrados).")
                except Exception:
                    pass

        # processar profiles conforme regras
        profiles_result = {"copied": [], "skipped": [], "errors": []}
        if profiles_dirs:
            profile_copy_plan = prepare_profiles_copy_list(profiles_dirs)
            conflicts = [os.path.basename(x["dest"]) for x in profile_copy_plan if x["exists"]]
            if conflicts:
                decision_event = threading.Event()
                decision = {"overwrite": False}
                def ask_on_main():
                    try:
                        ans = ask_overwrite_profiles(conflicts)
                        decision["overwrite"] = bool(ans)
                    except Exception:
                        decision["overwrite"] = False
                    finally:
                        decision_event.set()
                try:
                    root.after(0, ask_on_main)
                except Exception:
                    decision["overwrite"] = False
                    decision_event.set()
                decision_event.wait()
                overwrite = decision["overwrite"]
            else:
                overwrite = False
            profiles_result = copy_profiles_with_decision(profile_copy_plan, overwrite=overwrite)
        else:
            # nenhuma pasta de profiles encontrada
            write_log(f"{mod['name']}: Nenhuma pasta 'perfil' encontrada no pacote.")

        # compor resumo e mensagens finais
        parts = []
        # mods resumo
        if mods_dirs:
            # se pasta mods existia mas vazia -> registrar 0 mods
            if mods_detected_count == 0:
                parts.append("0 mods encontrados (pasta mods vazia)")
            else:
                parts.append(f"{mods_detected_count} itens copiados para mod/")
        else:
            parts.append("0 mods encontrados (nenhuma pasta 'mods' no pacote)")

        # profiles resumo
        if profiles_result.get("copied"):
            parts.append(f"{len(profiles_result['copied'])} profiles copiados")
        if profiles_result.get("skipped"):
            parts.append(f"{len(profiles_result['skipped'])} profiles ignorados (não substituídos)")
        if profiles_result.get("errors"):
            parts.append(f"{len(profiles_result['errors'])} erros ao copiar profiles")

        info = " / ".join(parts)
        write_log(f"{mod['name']}: Resultado - {info}")
        # notificar usuário com resumo
        try:
            messagebox.showinfo("Resumo da Instalação", f"{mod['name']}: {info}")
        except Exception:
            pass

        success = True
        details = {"mods": copied_mods_info, "profiles": profiles_result}

    except Exception as e:
        write_log(f"{mod['name']}: ERRO inesperado - {e}")
        success = False
        info = f"Erro inesperado: {e}"
        details = {"exception": str(e)}
    finally:
        try:
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
        except:
            pass
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except:
            pass
        DOWNLOADING = False
        cancel_flag = False
        try:
            root.after(0, lambda: modal.destroy())
        except:
            pass
        if on_complete:
            try:
                root.after(0, lambda: on_complete(success, info, details))
            except:
                pass

# ---------- Baixar RAW (download sem instalar) ----------
def baixar_raw_for_selected():
    sel = tree.selection()
    if not sel:
        messagebox.showinfo("Selecionar", "Escolha uma expansão para baixar o RAW.")
        return
    if len(sel) > 1:
        messagebox.showinfo("Selecionar", "Selecione apenas um item para 'Baixar RAW' por vez.")
        return
    idx = int(sel[0])
    mod = mods_list[idx]

    # Termos / aviso
    terms = (
        "AVISO - Baixar RAW\n\n"
        "Você pediu para baixar o arquivo ZIP bruto (RAW) para a pasta de Downloads do seu computador.\n\n"
        "Importante:\n"
        "- Este botão SOMENTE FAZ O DOWNLOAD do arquivo ZIP para a sua pasta Downloads.\n"
        "- O instalador NÃO fará nenhuma ação automática com esse arquivo (não extrai, não copia nada).\n"
        "- Você será responsável por inspecionar/manipular o arquivo manualmente.\n\n"
        "Deseja continuar e baixar o arquivo RAW para sua pasta Downloads?"
    )
    ok = messagebox.askyesno("Confirmar download RAW", terms)
    if not ok:
        write_log(f"Baixar RAW cancelado pelo usuário para {mod['name']}")
        return

    require_gdown_or_fail()
    out_name = (mod.get("filename") or mod['name'].replace(" ", "_")) + ".zip"
    out_path = os.path.join(DOWNLOADS_FOLDER, out_name)

    if os.path.exists(out_path):
        base, ext = os.path.splitext(out_name)
        i = 1
        while True:
            candidate = f"{base}_{i}{ext}"
            if not os.path.exists(os.path.join(DOWNLOADS_FOLDER, candidate)):
                out_path = os.path.join(DOWNLOADS_FOLDER, candidate)
                break
            i += 1

    # Modal
    modal = tk.Toplevel(root)
    modal.title(f"Baixando RAW: {mod['name']}")
    modal.geometry("420x140")
    modal.transient(root)
    modal.grab_set()

    status_text = tk.StringVar(value="Inicializando download RAW...")
    label = tk.Label(modal, textvariable=status_text, wraplength=380)
    label.pack(pady=8)
    prog = ttk.Progressbar(modal, orient="horizontal", length=360, mode="indeterminate")
    prog.pack(pady=6)
    prog.start(10)

    # botão fechar inicial escondido
    close_btn = tk.Button(modal, text="Fechar", state="disabled", command=modal.destroy)
    close_btn.pack(pady=6)

    def do_download_raw():
        try:
            robust_download_with_gdown(mod['drive_link'], out_path)
            write_log(f"RAW baixado para {out_path} (mod {mod['name']})")
            prog
            root.after(0, lambda: status_text.set(f"Download concluído!\nArquivo salvo em:\n{out_path}"))
        except Exception as e:
            write_log(f"Erro no Baixar RAW para {mod['name']}: {e}")
            root.after(0, lambda: status_text.set(f"Erro: {e}"))
        finally:
            prog["mode"] = "determinate"  # muda para modo determinado
            prog["value"] = 100           # barra cheia
            # habilitar botão fechar
            root.after(0, lambda: close_btn.config(state="normal"))


    threading.Thread(target=do_download_raw, daemon=True).start()


# ---------- UI helpers (similar anteriores) ----------
def create_modal_for_mod(mod):
    modal = tk.Toplevel(root)
    modal.title(f"Instalando {mod['name']}")
    modal.transient(root)
    modal.grab_set()
    modal.geometry("480x260")
    modal.resizable(False, False)
    try:
        modal.iconbitmap(os.path.abspath("icon.ico"))
    except Exception:
        pass
    status_text = tk.StringVar()
    status_text.set("Iniciando...")
    label = tk.Label(modal, textvariable=status_text, font=("Arial", 11), wraplength=440, justify="left")
    label.pack(pady=8)
    progress_bar = ttk.Progressbar(modal, orient="horizontal", length=420, mode="determinate")
    progress_bar.pack(pady=6)
    def cancel_operation():
        global cancel_flag
        cancel_flag = True
        status_text.set("Cancelando...")
    cancel_btn = tk.Button(modal, text="Cancelar", command=cancel_operation)
    cancel_btn.pack(pady=8)
    modal._status_text = status_text
    modal._progress_bar = progress_bar
    modal._cancel_btn = cancel_btn
    return modal

# ---------- fila / controles (mesmo) ----------
def enqueue_selected():
    sel = tree.selection()
    if not sel:
        messagebox.showinfo("Seleção", "Escolha pelo menos uma expansão para adicionar à fila.")
        return
    added = 0
    for s in sel:
        idx = int(s)
        mod = mods_list[idx]
        install_queue.append(mod)
        queue_listbox.insert("end", mod['name'])
        added += 1
    write_log(f"Adicionados {added} item(s) à fila.")
    messagebox.showinfo("Fila", f"{added} item(s) adicionados à fila.")

def clear_queue():
    global install_queue
    if queue_running:
        messagebox.showwarning("Fila", "A fila está em execução. Pare-a antes de limpar.")
        return
    install_queue = []
    queue_listbox.delete(0, "end")
    write_log("Fila limpa pelo usuário.")
    messagebox.showinfo("Fila", "Fila limpa.")

def stop_queue():
    global queue_stop_requested
    if not queue_running:
        messagebox.showinfo("Fila", "Nenhuma fila em execução.")
        return
    queue_stop_requested = True
    write_log("Solicitado parada da fila.")
    messagebox.showinfo("Fila", "Pedido de parada enviado. A operação em andamento será cancelada e a fila será parada.")

def start_queue():
    global queue_running, queue_stop_requested
    if queue_running:
        messagebox.showinfo("Fila", "Fila já está em execução.")
        return
    if not install_queue:
        messagebox.showinfo("Fila", "A fila está vazia.")
        return
    queue_running = True
    queue_stop_requested = False
    write_log("Iniciando execução da fila.")
    start_next_in_queue()

def start_next_in_queue():
    global queue_running, queue_stop_requested
    if queue_stop_requested:
        queue_running = False
        queue_stop_requested = False
        write_log("Fila parada pelo usuário.")
        messagebox.showinfo("Fila", "Fila parada.")
        return
    if not install_queue:
        queue_running = False
        write_log("Fila concluída.")
        messagebox.showinfo("Fila", "Todos os itens da fila foram processados.")
        return
    mod = install_queue.pop(0)
    queue_listbox.delete(0)
    modal = create_modal_for_mod(mod)
    status_text = modal._status_text
    progress_bar = modal._progress_bar
    cancel_btn = modal._cancel_btn

    def on_complete(success, info, details):
        ignored = details.get("profiles", {}).get("skipped", []) if details else []
        if success:
            if ignored:
                messagebox.showwarning("Concluído (com perfis ignorados)", f"{mod['name']} instalado com sucesso.\n{info}\nPerfis ignorados:\n" + "\n".join(ignored))
            else:
                messagebox.showinfo("Concluído", f"{mod['name']} instalado com sucesso.\n{info}")
        else:
            msg = info
            if ignored:
                msg += "\nPerfis ignorados:\n" + "\n".join(ignored)
            messagebox.showwarning("Finalizado", f"{mod['name']} finalizado com problema.\n{msg}")
        # atualizar lista de instalados
        root.after(300, refresh_installed_lists)
        root.after(300, start_next_in_queue)

    threading.Thread(target=download_and_install, args=(mod, status_text, modal, progress_bar, cancel_btn, on_complete), daemon=True).start()

def start_download_modal():
    sel = tree.selection()
    if not sel:
        messagebox.showinfo("Seleção", "Escolha uma expansão para instalar.")
        return
    if len(sel) > 1:
        if messagebox.askyesno("Múltiplos selecionados", "Você selecionou vários itens. Deseja adicioná-los à fila em vez de instalar um a um agora?"):
            enqueue_selected()
            return
    idx = int(sel[0])
    mod = mods_list[idx]
    modal = create_modal_for_mod(mod)
    status_text = modal._status_text
    progress_bar = modal._progress_bar
    cancel_btn = modal._cancel_btn

    def on_complete(success, info, details):
        ignored = details.get("profiles", {}).get("skipped", []) if details else []
        if success:
            if ignored:
                messagebox.showwarning("Concluído (com perfis ignorados)", f"{mod['name']} instalado com sucesso.\n{info}\nPerfis ignorados:\n" + "\n".join(ignored))
            else:
                messagebox.showinfo("Concluído", f"{mod['name']} instalado com sucesso.\n{info}")
        else:
            msg = info
            if ignored:
                msg += "\nPerfis ignorados:\n" + "\n".join(ignored)
            messagebox.showwarning("Finalizado", f"{mod['name']} finalizado com problema.\n{msg}")
        root.after(300, refresh_installed_lists)

    threading.Thread(target=download_and_install, args=(mod, status_text, modal, progress_bar, cancel_btn, on_complete), daemon=True).start()

# ---------- carregar lista remota ----------
def load_mods():
    global mods_list
    try:
        import requests
        response = requests.get(JSON_URL, timeout=10)
        response.raise_for_status()
        mods_list = response.json()
    except Exception as e:
        messagebox.showwarning("Aviso", f"Não foi possível acessar a lista de expansões. ({e})")
        write_log(f"Erro ao carregar mods.json: {e}")
        mods_list = []
    update_treeview()

def update_treeview(*args):
    search = search_var.get().lower()
    for i in tree.get_children():
        tree.delete(i)
    for idx, mod in enumerate(mods_list):
        if search in mod['name'].lower() or search in mod.get('description','').lower():
            tree.insert("", "end", iid=idx, values=(mod['name'], mod.get('description','')))

# ---------- aba instalados ----------
def refresh_installed_lists():
    try:
        mods_items = sorted(os.listdir(MODS_FOLDER))
    except Exception:
        mods_items = []
    installed_mods_listbox.delete(0, "end")
    for it in mods_items:
        installed_mods_listbox.insert("end", it)
    try:
        profiles_items = sorted(os.listdir(PROFILES_FOLDER))
    except Exception:
        profiles_items = []
    installed_profiles_listbox.delete(0, "end")
    for it in profiles_items:
        installed_profiles_listbox.insert("end", it)

def open_mod_folder():
    try:
        if sys.platform.startswith("win"):
            os.startfile(MODS_FOLDER)
        elif sys.platform.startswith("darwin"):
            os.system(f"open '{MODS_FOLDER}'")
        else:
            os.system(f"xdg-open '{MODS_FOLDER}'")
    except Exception as e:
        messagebox.showinfo("Abrir Pasta", f"Pasta de mods: {MODS_FOLDER}\nErro: {e}")

def open_profiles_folder():
    try:
        if sys.platform.startswith("win"):
            os.startfile(PROFILES_FOLDER)
        elif sys.platform.startswith("darwin"):
            os.system(f"open '{PROFILES_FOLDER}'")
        else:
            os.system(f"xdg-open '{PROFILES_FOLDER}'")
    except Exception as e:
        messagebox.showinfo("Abrir Pasta", f"Pasta de profiles: {PROFILES_FOLDER}\nErro: {e}")

def open_log_folder():
    try:
        if sys.platform.startswith("win"):
            os.startfile(LOG_FOLDER)
        elif sys.platform.startswith("darwin"):
            os.system(f"open '{LOG_FOLDER}'")
        else:
            os.system(f"xdg-open '{LOG_FOLDER}'")
    except Exception as e:
        messagebox.showinfo("Logs", f"Pasta de logs: {LOG_FOLDER}\nErro: {e}")

# ---------- GUI ----------
root = tk.Tk()
root.title("Instalador ETS2 - mods sobrescrevem, perfis confirmam")
root.geometry("1100x640")
try:
    root.iconbitmap(os.path.abspath("icon.ico"))
except Exception:
    pass

main_frame = tk.Frame(root)
main_frame.pack(fill="both", expand=True, padx=10, pady=10)

left_frame = tk.Frame(main_frame)
left_frame.pack(side="left", fill="both", expand=True)

search_frame = tk.Frame(left_frame)
search_frame.pack(fill="x", pady=5)
tk.Label(search_frame, text="Pesquisar:").pack(side="left")
search_var = tk.StringVar()
search_var.trace_add("write", update_treeview)
search_entry = tk.Entry(search_frame, textvariable=search_var)
search_entry.pack(side="left", fill="x", expand=True, padx=5)

list_frame = tk.LabelFrame(left_frame, text="Lista de Expansões Disponíveis")
list_frame.pack(fill="both", expand=True, pady=5)

columns = ("Nome","Descrição")
tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=25, selectmode="extended")
tree.heading("Nome", text="Nome")
tree.heading("Descrição", text="Descrição")
tree.column("Nome", width=380)
tree.column("Descrição", width=580)
tree.pack(side="left", fill="both", expand=True)

scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
tree.configure(yscroll=scrollbar.set)
scrollbar.pack(side="right", fill="y")

right_frame = tk.Frame(main_frame, width=360)
right_frame.pack(side="right", fill="y", padx=10)

notebook = ttk.Notebook(right_frame)
notebook.pack(fill="both", expand=True)

tab_queue = tk.Frame(notebook)
notebook.add(tab_queue, text="Fila / Controles")
tk.Label(tab_queue, text="Fila de Instalação:").pack(anchor="w", padx=6, pady=(6,0))
queue_listbox = tk.Listbox(tab_queue, height=10, width=50)
queue_listbox.pack(padx=6, pady=4)
queue_btn_frame = tk.Frame(tab_queue)
queue_btn_frame.pack(fill="x", pady=4, padx=6)
tk.Button(queue_btn_frame, text="Adicionar à Fila", command=enqueue_selected).pack(side="left", padx=3)
tk.Button(queue_btn_frame, text="Limpar Fila", command=clear_queue).pack(side="left", padx=3)
queue_action_frame = tk.Frame(tab_queue)
queue_action_frame.pack(fill="x", pady=4, padx=6)
tk.Button(queue_action_frame, text="Baixar Fila", command=start_queue).pack(side="left", padx=3)
tk.Button(queue_action_frame, text="Parar Fila", command=stop_queue).pack(side="left", padx=3)
button_frame = tk.Frame(tab_queue)
button_frame.pack(fill="x", pady=8, padx=6)
tk.Button(button_frame, text="Instalar Selecionado", command=start_download_modal).pack(fill="x", pady=3)
tk.Button(button_frame, text="Atualizar Lista", command=load_mods).pack(fill="x", pady=3)
# Novo botão Baixar RAW
tk.Button(button_frame, text="Baixar RAW", command=baixar_raw_for_selected).pack(fill="x", pady=3)

tab_installed = tk.Frame(notebook)
notebook.add(tab_installed, text="Instalados")
installed_mods_frame = tk.LabelFrame(tab_installed, text="Mods instalados (pasta mod/)")
installed_mods_frame.pack(fill="both", expand=True, padx=6, pady=6)
installed_mods_listbox = tk.Listbox(installed_mods_frame, height=8, width=60)
installed_mods_listbox.pack(side="left", fill="both", expand=True, padx=(6,0), pady=6)
mods_scroll = tk.Scrollbar(installed_mods_frame, orient="vertical", command=installed_mods_listbox.yview)
installed_mods_listbox.configure(yscroll=mods_scroll.set)
mods_scroll.pack(side="right", fill="y", pady=6)
installed_mods_btn_frame = tk.Frame(tab_installed)
installed_mods_btn_frame.pack(fill="x", padx=6)
tk.Button(installed_mods_btn_frame, text="Atualizar Mods Instalados", command=refresh_installed_lists).pack(side="left", padx=3)
tk.Button(installed_mods_btn_frame, text="Abrir pasta de mods", command=open_mod_folder).pack(side="left", padx=3)

installed_profiles_frame = tk.LabelFrame(tab_installed, text="Profiles instalados (pasta profiles/)")
installed_profiles_frame.pack(fill="both", expand=True, padx=6, pady=(0,6))
installed_profiles_listbox = tk.Listbox(installed_profiles_frame, height=8, width=60)
installed_profiles_listbox.pack(side="left", fill="both", expand=True, padx=(6,0), pady=6)
profiles_scroll = tk.Scrollbar(installed_profiles_frame, orient="vertical", command=installed_profiles_listbox.yview)
installed_profiles_listbox.configure(yscroll=profiles_scroll.set)
profiles_scroll.pack(side="right", fill="y", pady=6)
installed_profiles_btn_frame = tk.Frame(tab_installed)
installed_profiles_btn_frame.pack(fill="x", padx=6, pady=(0,6))
tk.Button(installed_profiles_btn_frame, text="Atualizar Profiles Instalados", command=refresh_installed_lists).pack(side="left", padx=3)
tk.Button(installed_profiles_btn_frame, text="Abrir pasta de profiles", command=open_profiles_folder).pack(side="left", padx=3)

tk.Button(right_frame, text="Abrir Pasta de Logs", command=open_log_folder).pack(pady=6, fill="x", padx=6)

# inicializa
load_mods()
write_log("Aplicativo iniciado (modo gdown).")
# atualizar lista de instalados na inicialização
root.after(500, refresh_installed_lists)
if not HAVE_GDOWN:
    try:
        messagebox.showwarning("gdown não instalado", "O pacote 'gdown' não está instalado. Instale com 'pip install gdown' para permitir downloads.")
    except:
        pass
root.mainloop()
