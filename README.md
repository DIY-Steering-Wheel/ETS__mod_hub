# ETS_ATS_mod_hub


# Como montar arquivos ZIP para o Instalador de Expansões ETS2

Este guia explica como organizar os arquivos dentro de um ZIP para que o instalador funcione corretamente. O instalador pode copiar arquivos de **mods**, **perfis** ou ambos para a pasta correta do Euro Truck Simulator 2.

---

## 1. Somente Mods

Se o conteúdo do ZIP for apenas mods, crie a seguinte estrutura:

```
meu_mod.zip
└── mods
    ├── arquivo1.scs
    ├── arquivo2.scs
    └── pasta_extra
        └── arquivo3.scs
```

- O instalador copiará todos os arquivos dentro da pasta `mods` para a pasta do jogo:
```
Documents\Euro Truck Simulator 2\mod
```
- **Subpastas** dentro de `mods` são copiadas normalmente.
- Não coloque arquivos soltos fora da pasta `mods`, senão serão ignorados.

---

## 2. Somente Perfil

Se o conteúdo do ZIP for apenas um perfil (savegame ou configuração), organize assim:

```
meu_perfil.zip
└── perfil
    ├── save.sii
    └── config.sii
```

- O instalador copiará todos os arquivos dentro da pasta `perfil` para a pasta de perfis:
```
Documents\Euro Truck Simulator 2\profiles
```
- Subpastas dentro de `perfil` também são copiadas normalmente.

---

## 3. Mods + Perfil juntos

Se quiser disponibilizar **mods e perfil no mesmo ZIP**, organize assim:

```
combo.zip
├── mods
│   ├── mod1.scs
│   └── mod2.scs
└── perfil
    ├── save.sii
    └── config.sii
```

- O instalador irá copiar **mods** para `mod/` e **perfil** para `profiles/`.
- Pode ter qualquer combinação de arquivos e subpastas dentro das pastas `mods` e `perfil`.

---

## Dicas importantes

1. **As pastas `mods` e `perfil` devem estar na raiz do ZIP.**
2. **Não colocar arquivos soltos fora das pastas**, pois o instalador não saberá para onde enviá-los.
3. **Subpastas são permitidas** e serão copiadas mantendo a estrutura.
4. Use nomes claros para identificar o conteúdo de cada ZIP.
5. Teste o ZIP localmente antes de disponibilizar para outros usuários.

---

> Seguindo estas instruções, o instalador funcionará corretamente e distribuirá os arquivos para as pastas certas no ETS2.
