# Requisitos de correção — v1.0-alpha.6

## Origem dos defeitos

O teste real usou os três relatórios semanais FlashList disponíveis no semestre
e os oito PDFs originais de slides, com 338 páginas. Ele também auditou as
saídas antigas que eram apresentadas como cursos.

Foram reproduzidos quatro defeitos:

1. ao receber `relatorio_semanal.pdf`, a alpha.5 produzia um V0 genérico; o
   mapa V1 precisa conferir as páginas, mas a execução não pode importar
   silenciosamente imagens vizinhas usadas como fila paralela;
2. a busca exata extensa teve recall zero em 84 consultas da semana 24–30/08,
   enquanto a passagem equivalente curta encontrou candidatos, muitos ruidosos;
3. saídas antigas aceitaram placeholders como `AnaliseRealSupremo` no campo de
   ID do YouTube e produziram links inexistentes;
4. outras saídas antigas declararam 35 unidades cobertas reciclando apenas
   quatro vídeos genéricos, sem evidência específica por exercício.

## Comportamento obrigatório

- Reconhecer um pacote `flashlist.weekly-study` somente quando a entrada for a
  pasta ou o `manifest.json`; PDF é sempre fonte autônoma.
- Criar exatamente uma fonte e uma unidade V0 por `item`, com identidade baseada
  no contexto, conteúdo estrutural e hash do asset, nunca apenas em `item_ref`.
- Mapear `easy` para `CONTROL_NO_AUTOMATIC`, `hard` para `OPTIONAL` e os demais
  estados reportados para `REQUIRED`.
- Se o asset ou OCR estiver ausente, preservar a unidade de resolução e marcar a
  lacuna; não transformar o cabeçalho do relatório em disciplina nem fingir que
  o enunciado foi lido.
- Manter a busca estrita e acrescentar uma consulta exata mínima, sem aspas e
  com a menor combinação ainda identificadora. Resultado continua sendo apenas
  candidato por metadados.
- Exigir exatamente 11 caracteres válidos em IDs diretos do YouTube. Termos,
  rótulos e placeholders nunca podem virar URLs de curso.
- Se duas unidades do mesmo candidato reutilizarem exatamente os mesmos
  intervalos e hashes de artefatos, falhar o gate `unit_specific_evidence`.
- Permitir registrar honestamente uma inspeção `UNVERIFIABLE` apenas visual sem
  inventar fala; essa exceção nunca pode promover conteúdo nem áudio.

## Critérios de aceite

- regressões automatizadas para os quatro defeitos;
- criação real a partir somente do PDF de 24–30/08, seguida de mapa V1 com 16
  unidades conferidas por página — 14 obrigatórias e dois controles, sem
  depender das imagens vizinhas;
- nenhuma rota liberada por metadado, URL sintaticamente válida ou frame sem
  fala/transcrição e áudio PT/EN realmente conferido;
- suíte offline, demo, validação de workspace, instalação limpa, validação da
  origem, manifesto e ZIP aprovados;
- resultados do piloto preservados fora da pasta versionada.
