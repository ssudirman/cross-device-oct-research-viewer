"""Minimal tested copy of the project SurfaceUNet inference architecture."""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


MIN_STD_PX = 0.10


class ConvBlock(nn.Module):
    def __init__(self, cin: int, cout: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv2d(cin, cout, 3, padding=1, bias=False),
            nn.InstanceNorm2d(cout, affine=True),
            nn.LeakyReLU(0.01, inplace=True),
            nn.Conv2d(cout, cout, 3, padding=1, bias=False),
            nn.InstanceNorm2d(cout, affine=True),
            nn.LeakyReLU(0.01, inplace=True),
        )

    def forward(self, x):
        return self.net(x)


class SurfaceUNet(nn.Module):
    def __init__(self, n_surfaces: int = 3, base: int = 32, levels: int = 5, max_channels: int = 512):
        super().__init__()
        channels = [min(base * 2 ** index, max_channels) for index in range(levels)]
        self.levels = levels
        self.enc = nn.ModuleList(
            ConvBlock(1 if index == 0 else channels[index - 1], channels[index])
            for index in range(levels)
        )
        self.pool = nn.MaxPool2d(2)
        self.up = nn.ModuleList(
            nn.ConvTranspose2d(channels[index + 1], channels[index], 2, stride=2)
            for index in range(levels - 1)
        )
        self.dec = nn.ModuleList(ConvBlock(2 * channels[index], channels[index]) for index in range(levels - 1))
        self.head = nn.Conv2d(channels[0], n_surfaces, 1)

    def forward(self, x):
        _, _, height, width = x.shape
        multiple = 2 ** (self.levels - 1)
        x = F.pad(x, (0, (-width) % multiple, 0, (-height) % multiple))
        skips = []
        for index, block in enumerate(self.enc):
            x = block(x)
            if index < self.levels - 1:
                skips.append(x)
                x = self.pool(x)
        for index in reversed(range(self.levels - 1)):
            x = self.dec[index](torch.cat([self.up[index](x), skips[index]], dim=1))
        return self.head(x)[:, :, :height, :width]


def surfaces_from_logits(logits):
    logp = F.log_softmax(logits.float(), dim=2)
    probability = logp.exp()
    rows = torch.arange(logits.shape[2], device=logits.device, dtype=torch.float32).view(1, 1, -1, 1)
    mean = (probability * rows).sum(dim=2)
    variance = (probability * (rows - mean.unsqueeze(2)) ** 2).sum(dim=2)
    std = torch.sqrt(variance + MIN_STD_PX ** 2)
    ordered = [mean[:, 0]]
    for surface in range(1, mean.shape[1]):
        ordered.append(ordered[-1] + F.relu(mean[:, surface] - ordered[-1]))
    return torch.stack(ordered, dim=1), std

