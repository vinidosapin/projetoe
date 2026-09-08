# Checklist de release — v1.0-alpha.6

## Árvore

- [x] pasta irmã isolada, com nome igual a `VERSION`;
- [x] alpha.5 e v4.7 conferidas por baseline, sem edição retroativa;
- [x] workspaces, fontes, imagens, vídeos, frames e transcrições fora da versão;
- [x] nenhum cache, bytecode, build, metadata de instalação ou arquivo oculto;
- [x] exatamente uma baseline direta: `alpha.5`.

## Produto

- [x] PDF explícito cobre somente o arquivo PDF;
- [x] pacote FlashList só é ativado por pasta ou manifesto explícito;
- [x] V0 não busca e V1 conferido continua obrigatório;
- [x] consulta mínima vem antes das tentativas qualificadas;
- [x] busca padrão seleciona somente `REQUIRED`;
- [x] `OPTIONAL` e controle exigem opt-in literal;
- [x] placeholder não pode virar ID de vídeo;
- [x] evidência idêntica não pode ser reciclada entre unidades;
- [x] metadados e legenda não aprovam conteúdo nem áudio;
- [x] conteúdo e faixa PT/EN permanecem gates independentes;
- [x] curso parcial mantém lacunas e tempo zero sem rota elegível.

## Verificação

- [x] 135 testes completos;
- [x] Ruff sem achados;
- [x] mypy sem achados em 33 arquivos;
- [x] demo e validação do workspace PDF-only;
- [x] execução real com uma fonte, 16 unidades e `valid=true`;
- [x] 77 candidatos tratados somente como metadados e zero rota liberada;
- [x] instalação limpa do núcleo e do extra, console e `pip check`;
- [x] validação da pasta com origem disponível;
- [x] ZIP com uma raiz, CRC, manifesto e hashes válidos;
- [x] reempacotamento byte a byte reproduzível;
- [x] instalação limpa a partir do ZIP e `pip check`.

## Distribuição

- [x] um ZIP homônimo ao lado de uma única pasta de versão;
- [x] tamanho abaixo de 500 MB decimais;
- [x] hashes externos registrados no catálogo da coleção;
- [x] `promotion_ready=false` no manifesto;
- [ ] promoção pedagógica — pendente de rotas aprovadas, especialistas e alunos.

Depois do ZIP final, não edite a pasta. Qualquer correção exige nova versão ou
novo fechamento integral com manifesto e ZIP regenerados.
