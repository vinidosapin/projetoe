# Notas de UX — v0.208-alpha.1

A interface foi reorganizada para que o aluno não precise varrer a árvore acadêmica completa e as opções de vídeo simultaneamente.

Decisões principais:

1. **Divulgação progressiva**: primeiro disciplina/área/módulo; depois tópicos; por fim, recursos do tópico selecionado.
2. **Hierarquia lateral rasa**: a barra lateral exibe no máximo duas camadas ao mesmo tempo (área e módulos da área ativa).
3. **Mestre-detalhe**: um único tópico ocupa o painel de estudo, mantendo contexto sem abrir dezenas de cards.
4. **Estado atual visível**: disciplina, área, módulo e tópico selecionados possuem estados ativos e breadcrumb.
5. **Acessibilidade**: foco visível, skip link, controles semânticos, labels e comportamento responsivo.
6. **Menos ruído visual**: métricas globais e detalhes de fonte foram retirados da camada primária e exibidos somente quando úteis.

Referências consultadas: Nielsen Norman Group (Progressive Disclosure), Carbon Design System (UI shell / side navigation), U.S. Web Design System (Side Navigation) e W3C WCAG 2.2.
