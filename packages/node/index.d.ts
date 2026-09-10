/** Offline geocoding for Chinese administrative regions. */

export type Level = "province" | "city" | "district";

export interface Region {
  name: string;
  /** 6-digit adcode. Always a string — leading zeros are significant. */
  code: string;
  level: Level;
  latitude: number;
  longitude: number;
}

export interface ReverseResult {
  province: Region | null;
  city: Region | null;
  district: Region | null;
}

export interface TreeNode {
  /** 6-digit adcode. */
  value: string;
  label: string;
  /** Absent on district (leaf) nodes. */
  children?: TreeNode[];
}

export interface SearchOptions {
  level?: Level;
  /** Province name or adcode. */
  province?: string;
  /** City name or adcode. */
  city?: string;
  /** Substring match when no exact match is found. Defaults to true. */
  fuzzy?: boolean;
}

export class GeoTool {
  /** @param dataPath Path to a .gtc file. Defaults to the bundled dataset. */
  constructor(dataPath?: string);

  reverse(lat: number, lng: number): ReverseResult;
  reverseBatch(coords: Array<[number, number]>): ReverseResult[];
  search(query: string, options?: SearchOptions): Region[];
  listRegions(level: Level): Region[];
  getRegion(code: string): Region | null;
  lookupAdcode(adcode: string): ReverseResult | null;
  isInChina(lat: number, lng: number): boolean;
  /** @throws {TypeError} if the adcode is malformed or unknown. */
  isInRegion(lat: number, lng: number, adcode: string): boolean;
}

export function reverse(lat: number, lng: number): ReverseResult;
export function reverseBatch(coords: Array<[number, number]>): ReverseResult[];
export function search(query: string, options?: SearchOptions): Region[];
export function listRegions(level: Level): Region[];
export function getRegion(code: string): Region | null;
export function lookupAdcode(adcode: string): ReverseResult | null;
export function isInChina(lat: number, lng: number): boolean;
export function isInRegion(lat: number, lng: number, adcode: string): boolean;

export function getAdministrativeTree(): TreeNode[];

/**
 * Coordinate conversions.
 *
 * These take **longitude first** and return `[lng, lat]`, unlike `distance`
 * and the `GeoTool` methods which take latitude first. Passing them the wrong
 * way round does not throw: the swapped longitude falls outside the China
 * bounding box, so the input is returned unchanged.
 */
export function wgs84ToGcj02(lng: number, lat: number): [number, number];
export function gcj02ToWgs84(lng: number, lat: number): [number, number];
export function gcj02ToBd09(lng: number, lat: number): [number, number];
export function bd09ToGcj02(lng: number, lat: number): [number, number];
export function wgs84ToBd09(lng: number, lat: number): [number, number];
export function bd09ToWgs84(lng: number, lat: number): [number, number];

/** Great-circle distance in kilometres. Latitude first. */
export function distance(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number,
): number;

export class GTCFormatError extends Error {}
export class GeometryUnavailable extends Error {}
