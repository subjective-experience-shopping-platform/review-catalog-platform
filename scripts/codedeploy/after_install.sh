#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=scripts/codedeploy/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if [[ -d "${release_dir}" ]]; then
  exit 0
fi

if [[ ! -f "${shared_models}/snunlp--KR-SBERT-Medium-extended-klueNLItriplet_PARpair_QApair-klueSTS/model.safetensors" ]]; then
  echo "provision the current SBERT snapshot in ${shared_models} before deployment; see AGENTS.md#모델-자산" >&2
  exit 1
fi

cp -a "${bundle_root}/." "${stage_dir}/"
rm -rf -- "${stage_dir}/models"
ln -s "${shared_models}" "${stage_dir}/models"
mv "${stage_dir}" "${release_dir}"
