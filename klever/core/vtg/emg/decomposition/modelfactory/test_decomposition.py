#
# Copyright (c) 2019 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import pytest
import logging

from klever.core.vtg.emg.decomposition.modelfactory import ModelFactory
from klever.core.vtg.emg.decomposition.separation import SeparationStrategy
from klever.core.vtg.emg.common.process.model_for_testing import model_preset
from klever.core.vtg.emg.decomposition.separation.linear import LinearStrategy

@pytest.fixture
def model():
    return model_preset()


def test_default_models(model):
    separation = ModelFactory(logging, {})
    scenario_generator = SeparationStrategy(logging, dict())
    processes_to_scenarops = {str(process): scenario_generator(process.actions) for process in model.processes}
    models = separation(processes_to_scenarops, model)

    assert len(models) == 5
    