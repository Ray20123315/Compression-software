from __future__ import annotations
import queue, threading, tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from . import __author__, __version__
from .core import compress_archive, extract_archive, list_archive, verify_archive

PROFILE_LABELS={
 'Smart Media（有損・更小）':'smart',
 'AutoBest（Exact・最小優先）':'autobest',
 'Ultra（Exact・LZMA2 高壓縮）':'ultra',
 'Minecraft（Exact・MC 整合包）':'minecraft',
 'Balanced（Exact・平衡）':'balanced',
 'Fast（Exact・Zstd 快速）':'fast',
}
FORMAT_LABELS={'RAYZ（推薦）':'rayz','ZIP（高相容）':'zip','TAR.XZ（Unix 相容）':'tar.xz'}

def _human_size(v):
    s=float(v)
    for u in ('B','KiB','MiB','GiB','TiB'):
        if s<1024 or u=='TiB': return f'{s:.2f} {u}'
        s/=1024

class RayPackApp(tk.Tk):
    def __init__(self):
        super().__init__(); self.title(f'RayPack {__version__} — ray20123315'); self.geometry('980x700'); self.minsize(840,620)
        self.queue=queue.Queue(); self.inputs=[]; self._style(); self._ui(); self.after(120,self._pump)
    def _style(self):
        s=ttk.Style(self)
        if 'vista' in s.theme_names(): s.theme_use('vista')
        s.configure('Title.TLabel',font=('Segoe UI',20,'bold')); s.configure('Accent.TButton',font=('Segoe UI',10,'bold'),padding=(12,8)); s.configure('Treeview',rowheight=25)
    def _ui(self):
        h=ttk.Frame(self,padding=(18,14)); h.pack(fill='x'); ttk.Label(h,text='RayPack',style='Title.TLabel').pack(side='left'); ttk.Label(h,text=f'  v{__version__} | 作者：{__author__}').pack(side='right',pady=(8,0))
        n=ttk.Notebook(self); n.pack(fill='both',expand=True,padx=14,pady=(0,14)); self.ct=ttk.Frame(n,padding=14); self.et=ttk.Frame(n,padding=14); self.at=ttk.Frame(n,padding=20); n.add(self.ct,text='壓縮'); n.add(self.et,text='解壓 / 檢查'); n.add(self.at,text='關於'); self._compress_ui(); self._extract_ui(); self._about_ui()
    def _compress_ui(self):
        ttk.Label(self.ct,text='1. 選擇檔案或資料夾').pack(anchor='w'); lf=ttk.Frame(self.ct); lf.pack(fill='both',expand=True,pady=(6,10)); self.il=tk.Listbox(lf,selectmode='extended',font=('Segoe UI',10)); self.il.pack(side='left',fill='both',expand=True); sb=ttk.Scrollbar(lf,command=self.il.yview); sb.pack(side='right',fill='y'); self.il.configure(yscrollcommand=sb.set)
        b=ttk.Frame(self.ct); b.pack(fill='x',pady=(0,12)); ttk.Button(b,text='加入檔案',command=self._add_files).pack(side='left'); ttk.Button(b,text='加入資料夾',command=self._add_folder).pack(side='left',padx=6); ttk.Button(b,text='移除選取',command=self._remove).pack(side='left'); ttk.Button(b,text='清空',command=self._clear).pack(side='left',padx=6)
        g=ttk.Frame(self.ct); g.pack(fill='x'); g.columnconfigure(1,weight=1); self.ov=tk.StringVar(); self.fv=tk.StringVar(value='RAYZ（推薦）'); self.pv=tk.StringVar(value='AutoBest（Exact・最小優先）')
        ttk.Label(g,text='2. 輸出：').grid(row=0,column=0,sticky='w',pady=5); ttk.Entry(g,textvariable=self.ov).grid(row=0,column=1,sticky='ew',padx=8); ttk.Button(g,text='瀏覽',command=self._browse_output).grid(row=0,column=2)
        ttk.Label(g,text='3. 格式：').grid(row=1,column=0,sticky='w',pady=5); fb=ttk.Combobox(g,textvariable=self.fv,state='readonly',values=list(FORMAT_LABELS),width=31); fb.grid(row=1,column=1,sticky='w',padx=8); fb.bind('<<ComboboxSelected>>',lambda _:(self._ext(),self._note()))
        ttk.Label(g,text='4. 模式：').grid(row=2,column=0,sticky='w',pady=5); pb=ttk.Combobox(g,textvariable=self.pv,state='readonly',values=list(PROFILE_LABELS),width=31); pb.grid(row=2,column=1,sticky='w',padx=8); pb.bind('<<ComboboxSelected>>',lambda _:self._note())
        self.note=ttk.Label(g,wraplength=760,foreground='#555'); self.note.grid(row=3,column=0,columnspan=3,sticky='w',pady=(7,10)); self._note()
        a=ttk.Frame(self.ct); a.pack(fill='x'); self.cb=ttk.Button(a,text='開始壓縮',style='Accent.TButton',command=self._start_compress); self.cb.pack(side='left'); self.cp=ttk.Progressbar(a,maximum=100); self.cp.pack(side='left',fill='x',expand=True,padx=(12,0)); self.cs=ttk.Label(self.ct,text='就緒'); self.cs.pack(anchor='w',pady=(8,0))
    def _extract_ui(self):
        t=ttk.Frame(self.et); t.pack(fill='x'); t.columnconfigure(1,weight=1); self.av=tk.StringVar(); self.dv=tk.StringVar(); ttk.Label(t,text='封存檔：').grid(row=0,column=0); ttk.Entry(t,textvariable=self.av).grid(row=0,column=1,sticky='ew',padx=8); ttk.Button(t,text='瀏覽',command=self._browse_archive).grid(row=0,column=2); ttk.Label(t,text='解壓到：').grid(row=1,column=0,pady=8); ttk.Entry(t,textvariable=self.dv).grid(row=1,column=1,sticky='ew',padx=8); ttk.Button(t,text='瀏覽',command=self._browse_dest).grid(row=1,column=2)
        a=ttk.Frame(self.et); a.pack(fill='x',pady=(6,10)); ttk.Button(a,text='讀取內容',command=self._inspect).pack(side='left'); ttk.Button(a,text='驗證完整性',command=self._verify).pack(side='left',padx=6); self.eb=ttk.Button(a,text='開始解壓',style='Accent.TButton',command=self._start_extract); self.eb.pack(side='left')
        self.tree=ttk.Treeview(self.et,columns=('size','type'),show='tree headings'); self.tree.heading('#0',text='路徑'); self.tree.heading('size',text='大小'); self.tree.heading('type',text='類型'); self.tree.column('#0',width=620); self.tree.column('size',width=120,anchor='e'); self.tree.column('type',width=80,anchor='center'); self.tree.pack(fill='both',expand=True); self.ep=ttk.Progressbar(self.et,maximum=100); self.ep.pack(fill='x',pady=(10,0)); self.es=ttk.Label(self.et,text='就緒'); self.es.pack(anchor='w',pady=(6,0))
    def _about_ui(self):
        text=f'''RayPack {__version__}\n\n作者：{__author__}\nCopyright © 2026 ray20123315. All Rights Reserved.\n\nExact 模式：完整保存原始 bytes。\n\nSmart Media（有損）：可對 JPG/PNG、MP4、MP3 先降低解析度／取樣率／bitrate；解壓時恢復原始尺寸或 sample rate。被丟掉的原始細節無法憑空恢復，因此 Smart 明確標示為有損。若 Smart 最終 RAYZ 不比 Exact Ultra 小，RayPack 自動保留 Exact 候選。\n\nJAR/ZIP 只有在未簽章、未加密、無重複 entry 且結構安全時才做 logical optimization；否則自動 Exact fallback。'''; ttk.Label(self.at,text=text,wraplength=800,justify='left',font=('Segoe UI',11)).pack(anchor='nw')
    def _append(self,paths):
        for p in paths:
            if p and p not in self.inputs: self.inputs.append(p); self.il.insert('end',p)
        if self.inputs and not self.ov.get():
            b=Path(self.inputs[0]); self.ov.set(str(b.parent/f'{b.stem or b.name}.rayz'))
    def _add_files(self): self._append(filedialog.askopenfilenames(title='選擇檔案'))
    def _add_folder(self): self._append([filedialog.askdirectory(title='選擇資料夾')])
    def _remove(self):
        for i in reversed(self.il.curselection()): self.il.delete(i); del self.inputs[i]
    def _clear(self): self.inputs.clear(); self.il.delete(0,'end')
    def _browse_output(self):
        fmt=FORMAT_LABELS[self.fv.get()]; ext='.rayz' if fmt=='rayz' else '.zip' if fmt=='zip' else '.tar.xz'; p=filedialog.asksaveasfilename(defaultextension=ext)
        if p:self.ov.set(p)
    def _ext(self):
        c=self.ov.get().strip();
        if not c:return
        fmt=FORMAT_LABELS[self.fv.get()]; ext='.rayz' if fmt=='rayz' else '.zip' if fmt=='zip' else '.tar.xz'; p=Path(c); lower=p.name.lower()
        for k in ('.tar.xz','.rayz','.zip'):
            if lower.endswith(k): p=p.with_name(p.name[:-len(k)]+ext); break
        else:p=p.with_name(p.name+ext)
        self.ov.set(str(p))
    def _note(self):
        p=PROFILE_LABELS[self.pv.get()]; fmt=FORMAT_LABELS[self.fv.get()]; notes={'smart':'有損模式：圖片/影音可降低品質後保存，解壓只恢復尺寸/取樣率，不恢復被丟掉的細節。只支援 RAYZ；若沒有變小會自動退回 Exact。','autobest':'Exact：同一 solid TAR 比較 LZMA2 與 Brotli q11，選較小者。','ultra':'Exact：192 MiB LZMA2 dictionary。','minecraft':'Exact：依 Minecraft 資料型態排序 solid stream，不改寫 Mod/JAR。','balanced':'Exact：32 MiB LZMA2 dictionary。','fast':'Exact：Zstd level 12，多執行緒。'}; msg=notes[p]
        if p=='smart' and fmt!='rayz': msg+=' 請將格式切換為 RAYZ。'
        self.note.configure(text=msg)
    def _browse_archive(self):
        p=filedialog.askopenfilename(filetypes=[('支援格式','*.rayz *.zip *.jar *.mrpack *.mcpack *.tar.xz *.txz *.tar.gz *.tgz *.tar'),('所有檔案','*.*')]);
        if p:
            self.av.set(p); pp=Path(p); name=pp.name
            for e in ('.tar.xz','.tar.gz','.rayz','.zip','.txz','.tgz','.tar'):
                if name.lower().endswith(e): name=name[:-len(e)]; break
            self.dv.set(str(pp.parent/name))
    def _browse_dest(self):
        p=filedialog.askdirectory();
        if p:self.dv.set(p)
    def _busy(self,b): self.cb.configure(state='disabled' if b else 'normal'); self.eb.configure(state='disabled' if b else 'normal')
    def _run(self,fn): self._busy(True); threading.Thread(target=self._worker,args=(fn,),daemon=True).start()
    def _worker(self,fn):
        try:self.queue.put(('success',fn()))
        except Exception as e:self.queue.put(('error',e))
    def _prog(self,m,f): self.queue.put(('progress',(m,f)))
    def _start_compress(self):
        if not self.inputs:return messagebox.showwarning('RayPack','請先加入至少一個檔案或資料夾。')
        if not self.ov.get().strip():return messagebox.showwarning('RayPack','請指定輸出檔案。')
        fmt=FORMAT_LABELS[self.fv.get()]; profile=PROFILE_LABELS[self.pv.get()]
        if profile=='smart' and fmt!='rayz':return messagebox.showwarning('RayPack','Smart Media 只支援 RAYZ。')
        self.cp['value']=0; self._run(lambda:('compress',compress_archive(self.inputs,self.ov.get(),format=fmt,profile=profile,progress=self._prog)))
    def _start_extract(self):
        if not self.av.get().strip() or not self.dv.get().strip():return messagebox.showwarning('RayPack','請選擇封存檔與輸出資料夾。')
        self.ep['value']=0; self._run(lambda:('extract',extract_archive(self.av.get(),self.dv.get(),progress=self._prog)))
    def _inspect(self):
        if self.av.get().strip():self._run(lambda:('list',list_archive(self.av.get())))
    def _verify(self):
        if self.av.get().strip():self._run(lambda:('verify',verify_archive(self.av.get())))
    def _pump(self):
        try:
            while True:
                kind,p=self.queue.get_nowait()
                if kind=='progress':
                    m,f=p; self.cs.configure(text=m); self.es.configure(text=m)
                    if f is not None:self.cp['value']=f*100;self.ep['value']=f*100
                elif kind=='error':self._busy(False); self.cs.configure(text=f'失敗：{p}'); self.es.configure(text=f'失敗：{p}'); messagebox.showerror('RayPack',str(p))
                else:
                    self._busy(False); a,r=p
                    if a=='compress':
                        saving=100*(1-r.ratio) if r.input_bytes else 0; msg=f'完成：{r.output.name} | {_human_size(r.output_bytes)} | 節省 {saving:.2f}% | {r.codec}'; self.cs.configure(text=msg); self.cp['value']=100; messagebox.showinfo('RayPack',msg)
                    elif a=='extract':self.ep['value']=100;self.es.configure(text=f'解壓完成：{r}');messagebox.showinfo('RayPack',f'解壓完成：\n{r}')
                    elif a=='list':
                        self.tree.delete(*self.tree.get_children())
                        for x in r:self.tree.insert('', 'end', text=x.name, values=(_human_size(x.size),'資料夾' if x.is_dir else '檔案'))
                        self.es.configure(text=f'已讀取 {len(r)} 個項目')
                    elif a=='verify':self.es.configure(text='驗證通過' if r.get('ok') else '驗證失敗');messagebox.showinfo('RayPack','驗證通過。\n'+'\n'.join(f'{k}: {v}' for k,v in r.items() if k!='ok'))
        except queue.Empty:pass
        self.after(120,self._pump)
def main(): RayPackApp().mainloop()
if __name__=='__main__':main()
