---
library_name: transformers
license: apache-2.0
pipeline_tag: image-text-to-text
base_model:
- nerkyor/Qwen3.8-27B-Coder390-EfficientThink-Opus5.5-GPT6Astra-Grok4.7-DSV4Pro-K3-SFT-RLOO-MTP-DFlash2
tags:
- abliterated
- uncensored
- huihui
- qwen3
- imatrix

---

# huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF


This is an uncensored version of [nerkyor/Qwen3.8-27B-Coder390-EfficientThink-Opus5.5-GPT6Astra-Grok4.7-DSV4Pro-K3-SFT-RLOO-MTP-DFlash2](https://huggingface.co/nerkyor/Qwen3.8-27B-Coder390-EfficientThink-Opus5.5-GPT6Astra-Grok4.7-DSV4Pro-K3-SFT-RLOO-MTP-DFlash2) created with abliteration (see [remove-refusals-with-transformers](https://github.com/Sumandora/remove-refusals-with-transformers) to know more about it).
This is a crude, proof-of-concept implementation to remove refusals from an LLM model without using TransformerLens.

## Note
Only layers 2 to 52 have been ablated.

## llama.cpp
Use the latest [llama.cpp](https://github.com/ggml-org/llama.cpp),
```
llama-cli -m huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-IQ3_S3.gguf -c 262144
```

## GGUF
1. download [llama.cpp-b11540](https://github.com/ggml-org/llama.cpp/releases/tag/b11540)

2. download GGUF
```
hf download huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF --local-dir ./huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF
```

3. llama-imatrix
calibration1.txt, calibration2.txt, calibration3.txt come from [eaddario/imatrix-calibration](https://huggingface.co/datasets/eaddario/imatrix-calibration)
```
llama-imatrix -m huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-bf16.gguf -f huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF/calibration3.txt -o huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF/abliterated-imatrix3.gguf --chunk 512 --parse-special -b 2048 --no-ppl
```

4. llama-quantize
```
llama-quantize --allow-requantize --tensor-type-file huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF/tensor-type-allocation-IQ3_S.txt --imatrix huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF/abliterated-imatrix3.gguf huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-bf16.gguf huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-IQ3_S3.gguf Q3_K
```

5. llama-perplexity
```
llama-perplexity -m huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-IQ3_S3.gguf -c 8192 -b 2048 -ctk bf16 -ctv bf16 -f huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-GGUF/calibration2.txt
```

6. llama-perplexity (calibration1.txt)

model                                                                        | calibration      |  perplexity      | PPL                      | Gap               |
-----------------------------------------------------------------------------|------------------|------------------|--------------------------|-------------------|
nerkyor/Qwen3.8-27B-Coder390-EfficientThink.gguf                             |                  | calibration1.txt | PPL = 4.1744 +/- 0.00925 | + 0               |
huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-bf16.gguf   |                  | calibration1.txt | PPL = 4.1588 +/- 0.00916 | - 0.0156 + 0      |
huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-IQ3_S1.gguf | calibration1.txt | calibration1.txt | PPL = 4.1922 +/- 0.00928 | + 0.0178 + 0.0334 |
huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-IQ3_S2.gguf | calibration2.txt | calibration1.txt | PPL = 4.1864 +/- 0.00926 | + 0.0120 + 0.0276 |
huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-IQ3_S3.gguf | calibration3.txt | calibration1.txt | PPL = 4.1851 +/- 0.00925 | + 0.0107 + 0.0263 |

7. llama-perplexity (calibration2.txt)

model                                                                        | calibration      |  perplexity      | PPL                      | Gap               |
-----------------------------------------------------------------------------|------------------|------------------|--------------------------|-------------------|
nerkyor/Qwen3.8-27B-Coder390-EfficientThink.gguf                             |                  | calibration2.txt | PPL = 3.8816 +/- 0.00677 | + 0               |
huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-bf16.gguf   |                  | calibration2.txt | PPL = 3.8468 +/- 0.00664 | - 0.0348 + 0      |
huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-IQ3_S1.gguf | calibration1.txt | calibration2.txt | PPL = 3.8547 +/- 0.00665 | - 0.0269 + 0.0079 |
huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-IQ3_S2.gguf | calibration2.txt | calibration2.txt | PPL = 3.8495 +/- 0.00664 | - 0.0321 + 0.0027 |
huihui-ai/Huihui-Qwen3.8-27B-Coder390-EfficientThink-abliterated-IQ3_S3.gguf | calibration3.txt | calibration2.txt | PPL = 3.8458 +/- 0.00662 | - 0.0358 - 0.0010 |

8. calibration datasets

name              | imatrix                   |  size      | records |
------------------|---------------------------|------------|---------|
calibration1.txt  | abliterated-imatrix1.gguf |  8,139,994 | 18,749  |
calibration2.txt  | abliterated-imatrix2.gguf | 12,760,564 | 24,999  |
calibration3.txt  | abliterated-imatrix3.gguf | 22,079,008 | 37,449  |


### Usage Warnings


 - **Risk of Sensitive or Controversial Outputs**: This model’s safety filtering has been significantly reduced, potentially generating sensitive, controversial, or inappropriate content. Users should exercise caution and rigorously review generated outputs.

 - **Not Suitable for All Audiences**: Due to limited content filtering, the model’s outputs may be inappropriate for public settings, underage users, or applications requiring high security.

 - **Legal and Ethical Responsibilities**: Users must ensure their usage complies with local laws and ethical standards. Generated content may carry legal or ethical risks, and users are solely responsible for any consequences.

 - **Research and Experimental Use**: It is recommended to use this model for research, testing, or controlled environments, avoiding direct use in production or public-facing commercial applications.

 - **Monitoring and Review Recommendations**: Users are strongly advised to monitor model outputs in real-time and conduct manual reviews when necessary to prevent the dissemination of inappropriate content.

 - **No Default Safety Guarantees**: Unlike standard models, this model has not undergone rigorous safety optimization. huihui.ai bears no responsibility for any consequences arising from its use.


### Donation
##### Your donation helps us continue our further development and improvement, a cup of coffee can do it.
- bitcoin:
```
  bc1qqnkhuchxw0zqjh2ku3lu4hq45hc6gy84uk70ge
```
- Support our work on [Ko-fi](https://ko-fi.com/huihuiai)!

