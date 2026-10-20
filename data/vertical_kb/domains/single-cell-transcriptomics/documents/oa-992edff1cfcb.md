# Single-cell RNA-seq denoising using a deep count autoencoder

## Method
We propose a deep count autoencoder network (DCA) to denoise scRNA-seq datasets.
DCA takes the count distribution, overdispersion and sparsity of the data into account using a negative binomial noise model with or without zero-inflation, and nonlinear gene-gene dependencies are captured.

## Evaluation
Single-cell RNA sequencing (scRNA-seq) has enabled researchers to study gene expression at a cellular resolution.
Our method scales linearly with the number of cells and can, therefore, be applied to datasets of millions of cells.

## Finding
We demonstrate that DCA denoising improves a diverse set of typical scRNA-seq data analyses using simulated and real datasets.
DCA outperforms existing methods for data imputation in quality and speed, enhancing biological discovery.

## Provenance
本卡片为项目组依据 DOI 10.1038/s41467-018-07931-2 的出版社元数据与公开摘要所作释义，不是论文全文逐字摘录。方法、实验和结论须取得全文后复核。
