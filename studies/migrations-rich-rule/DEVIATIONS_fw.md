# Desvios do PREREG_fw.md

## D1 (21:06 UTC, antes de qualquer rótulo): ordem de import no `score_fw.py`
A primeira execução falhou no import: o `analysis_v5` carregava o ekbasis 0.1.17 instalado (sem `ekbasis.probes`)
antes das regras. Correção: as regras importam primeiro, com o clone 0.1.20. O `analysis_v5.product` passa então a usar
o `migrations` do clone.

Verificação sem rótulos: o veredito do EKB nos 739 itens (v5 + v6) é idêntico com o ekbasis 0.1.17 e com o clone
(0 diferenças; script em /tmp/ekbv.py). Nenhum número muda por causa disso. O novo hash do `score_fw.py` está em
`FW_FREEZE2.sha256`. Nenhum rótulo foi lido antes desta correção: a execução falhou no import.
