# Sync com o Loom público (upstream)

**Remote típico:** `upstream` → https://github.com/awslabs/loom  
**Fork:** https://github.com/jsmesquita/loom-ext  

Antes de puxar, leia [CHANGELOG-LOOM-FORK.md](../CHANGELOG-LOOM-FORK.md) e filtre
entradas **Core** — são os paths com risco de conflito.

## Fluxo sugerido

```bash
git fetch upstream
git checkout main          # ou a branch que rastreia upstream/main
git merge upstream/main    # ou: git rebase upstream/main na feature
```

1. Liste paths Core do changelog.
2. Para cada um: `git log upstream/main -- <path>` e compare com o nosso diff.
3. `local-runtime/**` e `local-runtime/docs/**` em geral **não** existem no upstream → poucos conflitos.
4. Após o merge, acrescente no changelog uma entrada “sync upstream” com data + SHA de `upstream/main`.

## Checklist pós-merge

- [ ] Backend sobe; testes IdP / MCP hub / local_invoke relevantes
- [ ] Frontend build; Extension Host carrega `@loom-ext/local-runtime`
- [ ] Overlay `local-runtime/compose/overlay.yml` ainda aplica
- [ ] Changelog atualizado se o sync tocou Core

## O que não fazer

- Não resolver conflitos “jogando fora” o Extension Host ou BFFs documentados no changelog sem decisão explícita
- Não mover docs do fork de volta para `docs/` na raiz “para ficar igual ao upstream”
